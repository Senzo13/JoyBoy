"""
LoRA trainer — DreamBooth-style fine-tuning avec peft + accelerate.
Supporte SDXL et Flux Dev, VRAM-aware.
"""
import os
import gc
import math
import time
import random
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import torch
import numpy as np
from PIL import Image


# ===== CONFIG =====

@dataclass
class TrainingConfig:
    folder: str                     # Dossier d'images (ex: training_data/mon_lora)
    base_model: str = "sdxl"        # "sdxl" ou "flux"
    lora_name: str = "my_lora"      # Nom de sortie
    steps: int = 1000               # Training steps
    rank: int = 16                  # LoRA rank
    output_dir: str = "trained_loras"
    learning_rate: float = 1e-4
    seed: int = 42


# VRAM-aware defaults par GPU tier
_VRAM_CONFIGS = {
    # (base_model, vram_tier): {resolution, batch, grad_accum, dtype, use_8bit_adam}
    ("sdxl", 8):   {"resolution": 512,  "batch": 1, "grad_accum": 4, "dtype": "fp16",  "adam_8bit": True},
    ("sdxl", 16):  {"resolution": 768,  "batch": 1, "grad_accum": 2, "dtype": "fp16",  "adam_8bit": True},
    ("sdxl", 20):  {"resolution": 1024, "batch": 1, "grad_accum": 1, "dtype": "bf16",  "adam_8bit": False},
    ("flux", 20):  {"resolution": 768,  "batch": 1, "grad_accum": 4, "dtype": "bf16",  "adam_8bit": True},
    ("flux", 40):  {"resolution": 1024, "batch": 1, "grad_accum": 2, "dtype": "bf16",  "adam_8bit": False},
}


def _get_vram_config(base_model: str, vram_gb: float) -> dict:
    """Sélectionne la config optimale selon le GPU."""
    if base_model == "flux":
        if vram_gb >= 40:
            return _VRAM_CONFIGS[("flux", 40)]
        return _VRAM_CONFIGS[("flux", 20)]
    else:
        if vram_gb >= 20:
            return _VRAM_CONFIGS[("sdxl", 20)]
        if vram_gb >= 16:
            return _VRAM_CONFIGS[("sdxl", 16)]
        return _VRAM_CONFIGS[("sdxl", 8)]


# ===== DATASET =====

class CaptionDataset(torch.utils.data.Dataset):
    """Dataset simple: images + captions .txt adjacents."""

    EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}

    def __init__(self, folder: str, resolution: int, tokenizer=None, tokenizer_2=None, is_flux=False):
        self.folder = Path(folder)
        self.resolution = resolution
        self.tokenizer = tokenizer
        self.tokenizer_2 = tokenizer_2
        self.is_flux = is_flux

        # Lister les images
        self.image_paths = sorted([
            p for p in self.folder.iterdir()
            if p.suffix.lower() in self.EXTENSIONS
        ])
        if not self.image_paths:
            raise ValueError(f"Aucune image trouvée dans {folder}")

        print(f"[TRAIN] Dataset: {len(self.image_paths)} images, resolution={resolution}")

    def __len__(self):
        return len(self.image_paths)

    def _load_caption(self, img_path: Path) -> str:
        """Charge le fichier .txt caption associé à l'image."""
        txt_path = img_path.with_suffix('.txt')
        if txt_path.exists():
            return txt_path.read_text(encoding='utf-8').strip()
        return ""

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        caption = self._load_caption(img_path)

        # Charger et préprocesser l'image
        image = Image.open(img_path).convert('RGB')
        image = self._preprocess(image)

        # Convertir en tensor [-1, 1]
        image_tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float() / 127.5 - 1.0

        return {"pixel_values": image_tensor, "caption": caption}

    def _preprocess(self, image: Image.Image) -> Image.Image:
        """Resize + center crop à self.resolution."""
        w, h = image.size
        scale = self.resolution / min(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        image = image.resize((new_w, new_h), Image.LANCZOS)

        # Center crop
        left = (new_w - self.resolution) // 2
        top = (new_h - self.resolution) // 2
        image = image.crop((left, top, left + self.resolution, top + self.resolution))

        # Random horizontal flip
        if random.random() > 0.5:
            image = image.transpose(Image.FLIP_LEFT_RIGHT)

        return image


# ===== TRAINER =====

class LoRATrainer:
    """Entraîne un LoRA sur SDXL ou Flux Dev."""

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.should_stop = False
        self._status = {
            "running": False,
            "progress": 0.0,
            "step": 0,
            "total_steps": config.steps,
            "loss": 0.0,
            "eta": "",
            "log_lines": [],
        }

    @property
    def status(self):
        return self._status.copy()

    def _log(self, msg: str):
        """Ajoute une ligne au log (gardé dans status pour le frontend)."""
        print(f"[TRAIN] {msg}")
        self._status["log_lines"].append(msg)
        # Garder les 100 dernières lignes
        if len(self._status["log_lines"]) > 100:
            self._status["log_lines"] = self._status["log_lines"][-100:]

    def stop(self):
        """Demande l'arrêt propre de l'entraînement."""
        self.should_stop = True
        self._log("Arrêt demandé...")

    def train(self, progress_callback: Optional[Callable] = None):
        """
        Lance l'entraînement LoRA complet.
        Appelé dans un thread background.
        """
        self._status["running"] = True
        self._status["step"] = 0
        self._status["progress"] = 0.0
        self._status["log_lines"] = []
        config = self.config

        try:
            self._train_impl(progress_callback)
        except Exception as e:
            import traceback
            self._log(f"ERREUR: {e}")
            traceback.print_exc()
        finally:
            self._status["running"] = False
            self._cleanup()

    def _train_impl(self, progress_callback):
        """Implémentation interne de l'entraînement."""
        from core.models.registry import VRAM_GB

        config = self.config
        vram_cfg = _get_vram_config(config.base_model, VRAM_GB)
        resolution = vram_cfg["resolution"]
        grad_accum = vram_cfg["grad_accum"]
        use_8bit_adam = vram_cfg["adam_8bit"]
        dtype_str = vram_cfg["dtype"]
        dtype = torch.float16 if dtype_str == "fp16" else torch.bfloat16

        self._log(f"Config: {config.base_model}, rank={config.rank}, {resolution}px, {dtype_str}")
        self._log(f"VRAM: {VRAM_GB}GB, grad_accum={grad_accum}, 8bit_adam={use_8bit_adam}")
        self._log(f"Steps: {config.steps}, LR: {config.learning_rate}")

        # 1. Libérer la VRAM (décharger tous les modèles de génération)
        self._log("Libération VRAM...")
        self._unload_generation_models()

        # 2. Charger le modèle de base
        self._log(f"Chargement du modèle de base ({config.base_model})...")
        pipe, tokenizer, tokenizer_2, text_encoder, text_encoder_2, vae, unet = \
            self._load_base_model(config.base_model, dtype)

        # 3. Préparer le dataset
        is_flux = config.base_model == "flux"
        dataset = CaptionDataset(
            config.folder, resolution,
            tokenizer=tokenizer, tokenizer_2=tokenizer_2,
            is_flux=is_flux,
        )
        dataloader = torch.utils.data.DataLoader(
            dataset, batch_size=1, shuffle=True, num_workers=0,
        )

        # 4. Appliquer LoRA via peft
        self._log(f"Application LoRA (rank={config.rank})...")
        from peft import LoraConfig, get_peft_model

        # Attention + feedforward layers pour un LoRA plus expressif
        if is_flux:
            target_modules = ["to_q", "to_k", "to_v", "to_out.0",
                              "ff.net.0.proj", "ff.net.2"]
        else:
            # SDXL: attention + feedforward (comme kohya_ss defaults)
            target_modules = ["to_q", "to_k", "to_v", "to_out.0",
                              "ff.net.0.proj", "ff.net.2"]

        lora_config = LoraConfig(
            r=config.rank,
            lora_alpha=config.rank,
            target_modules=target_modules,
            lora_dropout=0.0,
            bias="none",
        )

        unet = get_peft_model(unet, lora_config)
        trainable_params = sum(p.numel() for p in unet.parameters() if p.requires_grad)
        total_params = sum(p.numel() for p in unet.parameters())
        self._log(f"LoRA params: {trainable_params:,} / {total_params:,} ({100*trainable_params/total_params:.2f}%)")

        # Gradient checkpointing pour économiser la VRAM
        if hasattr(unet, 'enable_gradient_checkpointing'):
            unet.enable_gradient_checkpointing()

        # 5. Optimiseur
        if use_8bit_adam:
            try:
                import bitsandbytes as bnb
                optimizer = bnb.optim.AdamW8bit(
                    unet.parameters(), lr=config.learning_rate, weight_decay=1e-2,
                )
                self._log("Optimiseur: AdamW 8-bit")
            except ImportError:
                self._log("bitsandbytes non disponible, fallback AdamW standard")
                optimizer = torch.optim.AdamW(
                    unet.parameters(), lr=config.learning_rate, weight_decay=1e-2,
                )
        else:
            optimizer = torch.optim.AdamW(
                unet.parameters(), lr=config.learning_rate, weight_decay=1e-2,
            )
            self._log("Optimiseur: AdamW standard")

        # Cosine LR scheduler
        from torch.optim.lr_scheduler import CosineAnnealingLR
        scheduler = CosineAnnealingLR(optimizer, T_max=config.steps, eta_min=config.learning_rate * 0.1)

        # Noise scheduler
        from diffusers import DDPMScheduler
        noise_scheduler = DDPMScheduler.from_config(pipe.scheduler.config)

        # 6. Freeze text encoders et VAE
        vae.requires_grad_(False)
        text_encoder.requires_grad_(False)
        if text_encoder_2 is not None:
            text_encoder_2.requires_grad_(False)

        # Move VAE et text encoders sur device
        device = "cuda"
        vae.to(device, dtype=torch.float32)  # VAE toujours en float32
        text_encoder.to(device, dtype=dtype)
        if text_encoder_2 is not None:
            text_encoder_2.to(device, dtype=dtype)
        unet.to(device, dtype=dtype)
        unet.train()

        # 7. Training loop
        self._log("Début de l'entraînement...")
        global_step = 0
        data_iter = iter(dataloader)
        loss_accum = 0.0
        t_start = time.time()

        while global_step < config.steps:
            if self.should_stop:
                self._log("Entraînement interrompu par l'utilisateur.")
                break

            # Cycle sur le dataset
            try:
                batch = next(data_iter)
            except StopIteration:
                data_iter = iter(dataloader)
                batch = next(data_iter)

            pixel_values = batch["pixel_values"].to(device, dtype=torch.float32)
            captions = batch["caption"]

            # Encode les images en latents
            with torch.no_grad():
                latents = vae.encode(pixel_values).latent_dist.sample()
                latents = latents * vae.config.scaling_factor
                latents = latents.to(dtype=dtype)

            # Encode les prompts
            with torch.no_grad():
                if is_flux:
                    prompt_embeds = self._encode_prompt_flux(
                        captions[0], tokenizer, tokenizer_2,
                        text_encoder, text_encoder_2, device, dtype,
                    )
                else:
                    prompt_embeds, pooled = self._encode_prompt_sdxl(
                        captions[0], tokenizer, tokenizer_2,
                        text_encoder, text_encoder_2, device, dtype,
                    )

            # Ajouter du bruit
            noise = torch.randn_like(latents)
            timesteps = torch.randint(
                0, noise_scheduler.config.num_train_timesteps,
                (latents.shape[0],), device=device,
            ).long()
            noisy_latents = noise_scheduler.add_noise(latents, noise, timesteps)

            # Forward pass
            if is_flux:
                model_pred = unet(noisy_latents, timesteps, encoder_hidden_states=prompt_embeds).sample
            else:
                added_cond_kwargs = {
                    "text_embeds": pooled,
                    "time_ids": self._get_time_ids(resolution, device, dtype),
                }
                model_pred = unet(
                    noisy_latents, timesteps,
                    encoder_hidden_states=prompt_embeds,
                    added_cond_kwargs=added_cond_kwargs,
                ).sample

            # Loss (predict noise → MSE)
            loss = torch.nn.functional.mse_loss(model_pred.float(), noise.float(), reduction="mean")
            loss = loss / grad_accum
            loss.backward()

            loss_accum += loss.item()

            # Gradient accumulation step
            if (global_step + 1) % grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(unet.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

            global_step += 1

            # Update status
            self._status["step"] = global_step
            self._status["progress"] = global_step / config.steps
            self._status["loss"] = loss_accum / grad_accum if (global_step % grad_accum == 0) else loss_accum

            # Log every 50 steps
            if global_step % 50 == 0:
                elapsed = time.time() - t_start
                steps_per_sec = global_step / elapsed if elapsed > 0 else 0
                remaining = (config.steps - global_step) / steps_per_sec if steps_per_sec > 0 else 0
                eta_str = f"{int(remaining//60)}m{int(remaining%60):02d}s"
                avg_loss = loss_accum / min(global_step, 50)
                self._log(f"Step {global_step}/{config.steps} | loss={avg_loss:.4f} | {steps_per_sec:.2f} it/s | ETA {eta_str}")
                self._status["eta"] = eta_str
                loss_accum = 0.0

            if progress_callback:
                progress_callback(self._status)

        # 8. Sauvegarder le LoRA (même si arrêté par l'utilisateur)
        self._save_lora(unet, config)

        self._log("Terminé!")

    def _unload_generation_models(self):
        """Décharge tous les modèles de génération pour libérer la VRAM."""
        try:
            from core.model_manager import ModelManager
            mgr = ModelManager.get()
            mgr.unload_all()
        except Exception as e:
            self._log(f"Warning unload: {e}")

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

    def _load_base_model(self, base_model: str, dtype):
        """Charge le modèle de base et retourne les composants."""
        if base_model == "flux":
            return self._load_flux(dtype)
        return self._load_sdxl(dtype)

    def _load_sdxl(self, dtype):
        """Charge SDXL pour le fine-tuning."""
        from diffusers import StableDiffusionXLPipeline
        from core.models.registry import VRAM_GB

        model_id = "stabilityai/stable-diffusion-xl-base-1.0"
        self._log(f"Chargement SDXL depuis {model_id}...")

        pipe = StableDiffusionXLPipeline.from_pretrained(
            model_id, torch_dtype=dtype, variant="fp16" if dtype == torch.float16 else None,
        )

        tokenizer = pipe.tokenizer
        tokenizer_2 = pipe.tokenizer_2
        text_encoder = pipe.text_encoder
        text_encoder_2 = pipe.text_encoder_2
        vae = pipe.vae
        unet = pipe.unet

        self._log("SDXL chargé")
        return pipe, tokenizer, tokenizer_2, text_encoder, text_encoder_2, vae, unet

    def _load_flux(self, dtype):
        """Charge Flux Dev pour le fine-tuning."""
        from diffusers import FluxPipeline
        from core.models.registry import VRAM_GB, FLUX_DEV_NF4_REPO

        if VRAM_GB < 20:
            self._log("Flux nécessite 20GB+ VRAM!")
            raise RuntimeError("Flux Dev nécessite au moins 20GB de VRAM")

        # Flux Dev NF4 pour le training (économise VRAM)
        model_id = "black-forest-labs/FLUX.1-dev"
        self._log(f"Chargement Flux Dev depuis {model_id}...")

        pipe = FluxPipeline.from_pretrained(
            model_id, torch_dtype=dtype,
        )

        tokenizer = pipe.tokenizer
        tokenizer_2 = pipe.tokenizer_2
        text_encoder = pipe.text_encoder
        text_encoder_2 = pipe.text_encoder_2
        vae = pipe.vae
        unet = pipe.transformer  # Flux utilise un transformer, pas un UNet

        self._log("Flux Dev chargé")
        return pipe, tokenizer, tokenizer_2, text_encoder, text_encoder_2, vae, unet

    def _encode_prompt_sdxl(self, prompt, tokenizer, tokenizer_2, text_encoder, text_encoder_2, device, dtype):
        """Encode un prompt pour SDXL (dual text encoders)."""
        # Tokenizer 1
        tokens_1 = tokenizer(
            prompt, padding="max_length", max_length=tokenizer.model_max_length,
            truncation=True, return_tensors="pt",
        ).input_ids.to(device)
        encoder_output_1 = text_encoder(tokens_1, output_hidden_states=True)
        prompt_embeds_1 = encoder_output_1.hidden_states[-2]

        # Tokenizer 2
        tokens_2 = tokenizer_2(
            prompt, padding="max_length", max_length=tokenizer_2.model_max_length,
            truncation=True, return_tensors="pt",
        ).input_ids.to(device)
        encoder_output_2 = text_encoder_2(tokens_2, output_hidden_states=True)
        prompt_embeds_2 = encoder_output_2.hidden_states[-2]
        pooled_prompt_embeds = encoder_output_2[0]

        prompt_embeds = torch.cat([prompt_embeds_1, prompt_embeds_2], dim=-1)
        return prompt_embeds.to(dtype=dtype), pooled_prompt_embeds.to(dtype=dtype)

    def _encode_prompt_flux(self, prompt, tokenizer, tokenizer_2, text_encoder, text_encoder_2, device, dtype):
        """Encode un prompt pour Flux (CLIP + T5)."""
        # CLIP (tokenizer 1)
        tokens = tokenizer(
            prompt, padding="max_length", max_length=tokenizer.model_max_length,
            truncation=True, return_tensors="pt",
        ).input_ids.to(device)
        prompt_embeds = text_encoder(tokens, output_hidden_states=False)[0]

        # T5 (tokenizer 2)
        tokens_2 = tokenizer_2(
            prompt, padding="max_length", max_length=512,
            truncation=True, return_tensors="pt",
        ).input_ids.to(device)
        prompt_embeds_2 = text_encoder_2(tokens_2)[0]

        # Concat ou utiliser T5 seul selon l'architecture
        return prompt_embeds_2.to(dtype=dtype)

    def _get_time_ids(self, resolution, device, dtype):
        """Génère les time_ids pour SDXL."""
        original_size = (resolution, resolution)
        crops_coords_top_left = (0, 0)
        target_size = (resolution, resolution)
        add_time_ids = torch.tensor(
            [list(original_size) + list(crops_coords_top_left) + list(target_size)],
            dtype=dtype, device=device,
        )
        return add_time_ids

    def _save_lora(self, unet, config):
        """Sauvegarde les poids LoRA en .safetensors (format diffusers)."""
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{config.lora_name}.safetensors"

        self._log(f"Sauvegarde LoRA → {output_path}")

        # Extraire les poids LoRA via peft
        from peft import get_peft_model_state_dict
        peft_state_dict = get_peft_model_state_dict(unet)

        # Convertir les clés peft → format diffusers (load_lora_weights compatible)
        # peft: "base_model.model.mid_block.attentions.0...to_q.lora_A.weight"
        # diffusers: "unet.mid_block.attentions.0...to_q.lora_A.weight"
        prefix = "unet." if config.base_model != "flux" else "transformer."
        diffusers_state_dict = {}
        for key, value in peft_state_dict.items():
            # Retirer "base_model.model." si présent
            new_key = key.replace("base_model.model.", "")
            # Ajouter le préfixe diffusers
            new_key = prefix + new_key
            diffusers_state_dict[new_key] = value

        # Sauvegarder en safetensors
        from safetensors.torch import save_file
        save_file(diffusers_state_dict, str(output_path))

        size_mb = output_path.stat().st_size / (1024 * 1024)
        self._log(f"LoRA sauvegardé: {output_path.name} ({size_mb:.1f} MB)")

    def _cleanup(self):
        """Libère la VRAM après l'entraînement."""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        self._log("VRAM libérée")
