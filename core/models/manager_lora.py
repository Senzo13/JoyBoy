"""LoRA loading and adapter orchestration for ModelManager."""

import subprocess
import sys


class ModelManagerLoraMixin:
    # LoRA Flux registry: (civitai_version_id, filename, default_scale)
    FLUX_LORA_REGISTRY = {}

    # LoRA Flux HuggingFace: (repo_id, subfolder, weight_name, default_scale)
    FLUX_HF_LORA_REGISTRY = {
        "clothes_off": ("speedchemistry/lora", "Flux-Kontext", "clothes_remover_v0.safetensors", 0.0),
    }

    def _load_flux_loras(self):
        """Charge les LoRAs Flux."""
        if self._inpaint_pipe is None:
            return

        # Installer peft si nécessaire
        if not self._ensure_peft():
            print("[MM] LoRAs Flux désactivés (peft non disponible)")
            return

        # LoRAs depuis CivitAI
        for name, (version_id, filename, default_scale) in self.FLUX_LORA_REGISTRY.items():
            try:
                lora_path = self._download_civitai_lora(version_id, filename)
                print(f"[MM] Chargement LoRA Flux {name}...")
                self._inpaint_pipe.load_lora_weights(
                    lora_path,
                    adapter_name=name
                )
                self._loras_loaded[name] = True
                self._lora_scales[name] = default_scale
                print(f"[MM] LoRA Flux {name} chargé (scale={default_scale})")
            except Exception as e:
                print(f"[MM] LoRA Flux {name}: échec ({e})")
                self._loras_loaded[name] = False

        # LoRAs depuis HuggingFace (clothes removal, etc.)
        for name, (repo_id, subfolder, weight_name, default_scale) in self.FLUX_HF_LORA_REGISTRY.items():
            try:
                print(f"[MM] Chargement LoRA Flux {name} (HuggingFace, 344MB)...")
                self._inpaint_pipe.load_lora_weights(
                    repo_id,
                    subfolder=subfolder,
                    weight_name=weight_name,
                    adapter_name=name
                )
                self._loras_loaded[name] = True
                self._lora_scales[name] = default_scale
                print(f"[MM] LoRA Flux {name} chargé (scale={default_scale})")
            except Exception as e:
                print(f"[MM] LoRA Flux {name}: échec ({e})")
                self._loras_loaded[name] = False

        self._apply_lora_scales()

    def _download_civitai_lora(self, model_version_id, filename):
        """Télécharge un LoRA depuis CivitAI si pas déjà présent."""
        from pathlib import Path

        lora_dir = Path(__file__).parent.parent / "ext_weights" / "loras"
        lora_dir.mkdir(parents=True, exist_ok=True)
        lora_path = lora_dir / filename

        if lora_path.exists():
            print(f"[MM] LoRA déjà présent: {filename}")
            return str(lora_path)

        from config import CIVITAI_API_KEY
        api_key = CIVITAI_API_KEY
        url = f"https://civitai.com/api/download/models/{model_version_id}"
        if api_key:
            url += f"?token={api_key}"

        print(f"[MM] Téléchargement LoRA depuis CivitAI (version {model_version_id})...")
        import requests
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()

        total = int(resp.headers.get('content-length', 0))
        downloaded = 0
        with open(lora_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and downloaded % (50 * 1024 * 1024) < 8192:
                    pct = downloaded * 100 // total
                    print(f"[MM] LoRA download: {pct}%")

        size_mb = lora_path.stat().st_size / (1024 * 1024)
        print(f"[MM] LoRA téléchargé: {filename} ({size_mb:.0f}MB)")
        return str(lora_path)

    # LoRA registry: (civitai_version_id, filename, default_scale, trigger_word)
    # IMPORTANT: default_scale=0.0 pour TOUS les LoRAs — l'utilisateur doit les activer explicitement
    LORA_REGISTRY = {}

    _peft_checked = False
    _peft_available = False

    def _ensure_peft(self):
        """Vérifie que peft est disponible. Ne tente l'install qu'une seule fois."""
        if type(self)._peft_checked:
            return type(self)._peft_available
        type(self)._peft_checked = True
        try:
            import peft
            type(self)._peft_available = True
            return True
        except ImportError:
            print("[MM] peft manquant, tentative d'installation...")
            try:
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'peft'], check=True, capture_output=True)
                import peft
                print("[MM] peft installé avec succès")
                type(self)._peft_available = True
                return True
            except Exception as e:
                print(f"[MM] peft indisponible: {e}")
                print("[MM] → pip install peft pour activer les LoRAs")
                type(self)._peft_available = False
                return False

    def _load_all_loras(self):
        """Télécharge et charge tous les LoRAs du registry."""
        if self._inpaint_pipe is None:
            return

        # Installer peft si nécessaire
        if not self._ensure_peft():
            print("[MM] LoRAs désactivés (peft non disponible)")
            return

        for name, (version_id, filename, default_scale, trigger) in self.LORA_REGISTRY.items():
            try:
                lora_path = self._download_civitai_lora(version_id, filename)
                print(f"[MM] Chargement LoRA {name}...")
                self._inpaint_pipe.load_lora_weights(
                    lora_path,
                    adapter_name=name
                )
                self._loras_loaded[name] = True
                self._lora_scales[name] = default_scale
                print(f"[MM] LoRA {name} chargé (scale={default_scale})")
            except Exception as e:
                print(f"[MM] LoRA {name}: échec ({e})")
                self._loras_loaded[name] = False
                # Nettoyer l'adapter partiellement enregistré (évite "already in use")
                try:
                    self._inpaint_pipe.delete_adapters(name)
                except Exception:
                    pass

        # Appliquer les scales initiales
        self._apply_lora_scales()

    def _apply_lora_scales(self):
        """Applique les scales courantes de tous les LoRAs chargés (sans IP-Adapter)."""
        if self._inpaint_pipe is None:
            return
        active = [(n, s) for n, s in self._lora_scales.items() if self._loras_loaded.get(n)]
        if not active:
            return
        names, weights = zip(*active)
        try:
            self._inpaint_pipe.set_adapters(list(names), adapter_weights=list(weights))
            print(f"[MM] LoRA scales appliqués: {dict(zip(names, weights))}")
        except Exception as e:
            print(f"[MM] LoRA set_adapters error: {e}")

    def _apply_all_adapters(self):
        """Applique TOUS les adapters: LoRAs custom + built-in + IP-Adapter (faceid_0 etc.)."""
        if self._inpaint_pipe is None:
            return
        # Collecter les LoRAs actifs
        all_names = []
        all_weights = []
        for n, s in self._lora_scales.items():
            if self._loras_loaded.get(n):
                all_names.append(n)
                all_weights.append(s)
        # Ajouter les adapters IP-Adapter (faceid_0 etc.) s'ils existent
        try:
            target = getattr(self._inpaint_pipe, 'unet', None) or getattr(self._inpaint_pipe, 'transformer', None)
            if target is not None and hasattr(target, 'peft_config'):
                for adapter_name in target.peft_config:
                    if adapter_name not in all_names and adapter_name.startswith('faceid'):
                        all_names.append(adapter_name)
                        all_weights.append(1.0)  # IP-Adapter scale géré séparément
        except Exception:
            pass
        if not all_names:
            return
        try:
            self._inpaint_pipe.set_adapters(all_names, adapter_weights=all_weights)
            print(f"[MM] Adapters actifs: {dict(zip(all_names, all_weights))}")
        except Exception as e:
            print(f"[MM] set_adapters error: {e}")

    def _is_flux_pipeline(self):
        """Détecte si le pipeline actif est Flux (Fill ou Kontext)."""
        if self._inpaint_pipe is None:
            return False
        pipe_class = type(self._inpaint_pipe).__name__
        return 'Flux' in pipe_class

    def ensure_lora_loaded(self, name):
        """Charge un LoRA à la demande s'il n'est pas déjà chargé. Retourne True si chargé.
        Route automatiquement vers le bon registre (SDXL ou Flux) selon le pipeline actif."""
        if self._loras_loaded.get(name):
            return True
        if self._inpaint_pipe is None:
            return False
        if not self._ensure_peft():
            return False

        is_flux = self._is_flux_pipeline()

        if is_flux:
            # Mapping intentions SDXL → noms Flux (skin → clothes_off)
            flux_name = self._FLUX_LORA_NAME_MAP.get(name, name)
            if flux_name != name:
                # Vérifier si déjà chargé sous le nom Flux
                if self._loras_loaded.get(flux_name):
                    self._loras_loaded[name] = True
                    return True
                name = flux_name

            # Chercher dans FLUX_LORA_REGISTRY (CivitAI)
            if name in self.FLUX_LORA_REGISTRY:
                version_id, filename, default_scale = self.FLUX_LORA_REGISTRY[name]
                try:
                    lora_path = self._download_civitai_lora(version_id, filename)
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    print(f"[MM] Chargement LoRA Flux {name} (lazy)...")
                    self._inpaint_pipe.load_lora_weights(lora_path, adapter_name=name)
                    self._loras_loaded[name] = True
                    self._lora_scales[name] = default_scale
                    print(f"[MM] LoRA Flux {name} chargé")
                    return True
                except Exception as e:
                    print(f"[MM] LoRA Flux {name}: échec ({e})")
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    self._loras_loaded[name] = False
                    return False

            # Chercher dans FLUX_HF_LORA_REGISTRY (HuggingFace)
            if name in self.FLUX_HF_LORA_REGISTRY:
                repo_id, subfolder, weight_name, default_scale = self.FLUX_HF_LORA_REGISTRY[name]
                try:
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    print(f"[MM] Chargement LoRA Flux {name} (HuggingFace, lazy)...")
                    self._inpaint_pipe.load_lora_weights(
                        repo_id, subfolder=subfolder,
                        weight_name=weight_name, adapter_name=name
                    )
                    self._loras_loaded[name] = True
                    self._lora_scales[name] = default_scale
                    print(f"[MM] LoRA Flux {name} chargé")
                    return True
                except Exception as e:
                    print(f"[MM] LoRA Flux {name}: échec ({e})")
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    self._loras_loaded[name] = False
                    return False
        else:
            # Chercher dans LORA_REGISTRY (SDXL)
            if name in self.LORA_REGISTRY:
                version_id, filename, default_scale, trigger = self.LORA_REGISTRY[name]
                try:
                    lora_path = self._download_civitai_lora(version_id, filename)
                    # Nettoyer un adapter fantôme d'un chargement précédent échoué
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    print(f"[MM] Chargement LoRA {name} (lazy)...")
                    self._inpaint_pipe.load_lora_weights(lora_path, adapter_name=name)
                    self._loras_loaded[name] = True
                    self._lora_scales[name] = default_scale
                    print(f"[MM] LoRA {name} chargé")
                    return True
                except Exception as e:
                    print(f"[MM] LoRA {name}: échec ({e})")
                    try:
                        self._inpaint_pipe.delete_adapters(name)
                    except Exception:
                        pass
                    self._loras_loaded[name] = False
                    return False

        # Fallback: chercher dans trained_loras/ (custom LoRAs)
        custom_path = self._find_custom_lora(name)
        if custom_path:
            return self._load_custom_lora(name, custom_path)

        return False

    def _find_custom_lora(self, name):
        """Cherche un LoRA custom dans trained_loras/."""
        from pathlib import Path
        lora_dir = Path(__file__).parent.parent.parent / "trained_loras"
        if not lora_dir.exists():
            return None
        # Chercher par nom exact ou avec .safetensors
        for ext in ['.safetensors', '.pt', '.bin']:
            path = lora_dir / f"{name}{ext}"
            if path.exists():
                return str(path)
        # Chercher par prefix (sans extension)
        for f in lora_dir.iterdir():
            if f.stem == name and f.suffix in {'.safetensors', '.pt', '.bin'}:
                return str(f)
        return None

    def _load_custom_lora(self, name, lora_path, scale=0.8):
        """Charge un LoRA custom depuis un fichier local.
        Compatible avec IP-Adapter (préserve les adapters existants comme faceid_0).
        """
        if self._inpaint_pipe is None:
            return False
        try:
            # Sauvegarder les adapters existants (IP-Adapter etc.) AVANT modification
            existing_adapters = []
            try:
                existing_adapters = list(self._inpaint_pipe.get_active_adapters())
            except Exception:
                pass

            # Supprimer l'ancien adapter si déjà chargé (ignore erreurs)
            try:
                self._inpaint_pipe.delete_adapters(name)
            except Exception:
                pass

            # Restaurer les adapters existants après suppression
            # (delete_adapters peut changer l'adapter actif)
            if existing_adapters:
                remaining = [a for a in existing_adapters if a != name]
                if remaining:
                    try:
                        self._inpaint_pipe.set_adapters(remaining)
                    except Exception:
                        pass

            print(f"[MM] Chargement LoRA custom '{name}' depuis {lora_path}...")
            self._inpaint_pipe.load_lora_weights(lora_path, adapter_name=name)
            self._loras_loaded[name] = True
            self._lora_scales[name] = scale

            # Activer TOUS les adapters (custom LoRAs + IP-Adapter)
            self._apply_all_adapters()

            # Diagnostic: vérifier que les couches LoRA sont bien injectées
            lora_layers = 0
            target = getattr(self._inpaint_pipe, 'unet', None) or getattr(self._inpaint_pipe, 'transformer', None)
            if target is not None:
                for _, module in target.named_modules():
                    if hasattr(module, 'lora_A') and name in getattr(module, 'lora_A', {}):
                        lora_layers += 1
            active = []
            try:
                active = list(self._inpaint_pipe.get_active_adapters())
            except Exception:
                pass
            print(f"[MM] LoRA custom '{name}' chargé (scale={scale}, {lora_layers} couches, adapters actifs: {active})")
            return True
        except Exception as e:
            print(f"[MM] LoRA custom '{name}': échec ({e})")
            import traceback
            traceback.print_exc()
            try:
                self._inpaint_pipe.delete_adapters(name)
            except Exception:
                pass
            self._loras_loaded[name] = False
            return False

    def list_custom_loras(self):
        """Liste les LoRAs custom disponibles dans trained_loras/."""
        from pathlib import Path
        lora_dir = Path(__file__).parent.parent.parent / "trained_loras"
        if not lora_dir.exists():
            return []
        loras = []
        for f in sorted(lora_dir.iterdir()):
            if f.suffix in {'.safetensors', '.pt', '.bin'}:
                is_loaded = self._loras_loaded.get(f.stem, False)
                is_pending = f.stem in self._pending_custom_loras
                loras.append({
                    "name": f.stem,
                    "filename": f.name,
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                    "loaded": is_loaded or is_pending,
                    "pending": is_pending and not is_loaded,
                    "scale": self._lora_scales.get(f.stem, self._pending_custom_loras.get(f.stem, 0.8)),
                })
        return loras

    def _load_pending_custom_loras(self):
        """Charge les custom LoRAs en attente après un chargement de pipeline."""
        if not self._pending_custom_loras or self._inpaint_pipe is None:
            return
        if not self._ensure_peft():
            return
        loaded = []
        for name, scale in list(self._pending_custom_loras.items()):
            custom_path = self._find_custom_lora(name)
            if custom_path:
                if self._load_custom_lora(name, custom_path, scale=scale):
                    loaded.append(name)
                    print(f"[MM] Custom LoRA '{name}' chargé (pending, scale={scale})")
        # Nettoyer les pending qui ont été chargés
        for name in loaded:
            del self._pending_custom_loras[name]

    # Mapping intentions frontend → noms LoRA Flux réels
    _FLUX_LORA_NAME_MAP = {"skin": "clothes_off"}

    def set_lora_scale(self, name, scale):
        """Ajuste le scale d'un LoRA spécifique."""
        # Résoudre le nom réel pour Flux (skin → clothes_off)
        if self._is_flux_pipeline():
            name = self._FLUX_LORA_NAME_MAP.get(name, name)
        if not self._loras_loaded.get(name) or self._inpaint_pipe is None:
            return
        self._lora_scales[name] = scale
        self._apply_lora_scales()

    def unload_lora(self, name):
        """Décharge complètement un LoRA du pipeline (libère la VRAM)."""
        if self._is_flux_pipeline():
            name = self._FLUX_LORA_NAME_MAP.get(name, name)
        if not self._loras_loaded.get(name) or self._inpaint_pipe is None:
            return
        try:
            self._inpaint_pipe.delete_adapters(name)
            print(f"[MM] LoRA {name} déchargé (VRAM libérée)")
        except Exception as e:
            print(f"[MM] LoRA {name} unload error: {e}")
        self._loras_loaded[name] = False
        self._lora_scales.pop(name, None)
        # Réappliquer les adapters restants
        self._apply_lora_scales()

    def prepare_prompt_with_lora_triggers(self, prompt: str) -> str:
        """Ajoute les trigger words des LoRAs actifs au prompt.

        Un LoRA est considéré actif si son scale > 0 et qu'il est chargé.
        Le trigger word est ajouté au début du prompt s'il n'est pas déjà présent.
        """
        if not prompt:
            return prompt

        triggers_to_add = []
        for name, (_, _, _, trigger) in self.LORA_REGISTRY.items():
            if trigger and self._loras_loaded.get(name) and self._lora_scales.get(name, 0) > 0:
                # Vérifier si le trigger n'est pas déjà dans le prompt
                if trigger.lower() not in prompt.lower():
                    triggers_to_add.append(trigger)
                    print(f"[MM] LoRA {name} trigger ajouté: {trigger[:40]}...")

        if triggers_to_add:
            return ", ".join(triggers_to_add) + ", " + prompt
        return prompt


