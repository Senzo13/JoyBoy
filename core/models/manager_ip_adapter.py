"""IP-Adapter, InsightFace, and embedding helpers for ModelManager."""

import subprocess
import sys

import torch


class ModelManagerIPAdapterMixin:
    _face_analyzer = None  # InsightFace (singleton)
    _insightface_checked = False
    _insightface_available = False

    def _ensure_insightface(self):
        """Installe insightface si nécessaire, retourne True si disponible.
        Auto-fix: détecte les incompatibilités numpy binaires et reinstalle."""
        # Cache résultat — ne pas retenter chaque génération
        if type(self)._insightface_checked:
            return type(self)._insightface_available

        try:
            from insightface.app import FaceAnalysis
            type(self)._insightface_checked = True
            type(self)._insightface_available = True
            return True
        except ImportError:
            print("[MM] Installation de insightface...")
            return self._install_insightface()
        except Exception as e:
            err_msg = str(e)
            if 'dtype size changed' in err_msg or 'binary incompatibility' in err_msg:
                # numpy version mismatch → auto-fix par reinstallation
                print(f"[MM] insightface numpy incompatibility detected, auto-fixing...")
                return self._install_insightface(force=True)
            print(f"[MM] insightface indisponible: {e}")
            type(self)._insightface_checked = True
            type(self)._insightface_available = False
            return False

    def _install_insightface(self, force=False):
        """Installe ou reinstalle insightface. Retourne True si OK.
        Si numpy binary incompat → downgrade numpy <2.0 sur disque, skip cette session."""
        try:
            if not force:
                # Installation initiale (pas encore installé)
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', 'insightface', '--quiet'],
                    capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    wheel_url = "https://github.com/Gourieff/Assets/raw/main/Insightface/insightface-0.7.3-cp312-cp312-win_amd64.whl"
                    subprocess.run(
                        [sys.executable, '-m', 'pip', 'install', wheel_url, '--quiet'],
                        check=True, timeout=300)
                # Purger modules et re-importer
                for mod_name in list(sys.modules.keys()):
                    if 'insightface' in mod_name:
                        del sys.modules[mod_name]
                from insightface.app import FaceAnalysis
                print("[MM] insightface installé")
                type(self)._insightface_checked = True
                type(self)._insightface_available = True
                return True
            else:
                # numpy incompat → downgrade numpy sur disque SANS re-importer
                # (numpy 2.x déjà chargé en mémoire, ne pas toucher sys.modules)
                print("[MM] Downgrade numpy pour compatibilité insightface...")
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', 'numpy>=1.26,<2.0', '--quiet'],
                    capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    print("[MM] ✓ numpy downgraded sur disque → IP-Adapter FaceID actif au prochain démarrage")
                else:
                    print(f"[MM] numpy downgrade failed: {result.stderr[-300:]}")
                # Cette session: insightface indisponible (numpy 2.x en mémoire)
                type(self)._insightface_checked = True
                type(self)._insightface_available = False
                return False
        except Exception as e:
            print(f"[MM] insightface non disponible: {e}")
            type(self)._insightface_checked = True
            type(self)._insightface_available = False
            return False

    def _load_ip_adapter_face(self):
        """Charge IP-Adapter FaceID pour préserver le visage."""
        if self._ip_adapter_loaded:
            return

        if self._inpaint_pipe is None:
            print("[MM] Impossible de charger IP-Adapter: pas de pipeline inpaint")
            return

        # Installer insightface si nécessaire
        if not self._ensure_insightface():
            return

        print("[MM] Loading IP-Adapter FaceID...")
        try:
            self._inpaint_pipe.load_ip_adapter(
                "h94/IP-Adapter-FaceID",
                subfolder=None,
                weight_name="ip-adapter-faceid_sdxl.bin",
                image_encoder_folder=None,
            )
            # Aligner dtype des poids FaceID avec le UNet (fp16 vs bf16)
            unet_dtype = self._inpaint_pipe.unet.dtype
            if hasattr(self._inpaint_pipe.unet, 'encoder_hid_proj'):
                self._inpaint_pipe.unet.encoder_hid_proj.to(dtype=unet_dtype)
            self._ip_adapter_loaded = True
            print(f"[MM] Ready: IP-Adapter FaceID (dtype={unet_dtype}, scale set dynamically)")
        except Exception as e:
            print(f"[MM] IP-Adapter FaceID error: {e}")
            self._ip_adapter_loaded = False

    def _load_ip_adapter_style(self):
        """Charge IP-Adapter Plus (CLIP) pour style reference."""
        if self._ip_adapter_style_loaded:
            return

        # Décharger tout IP-Adapter existant d'abord
        if self._ip_adapter_loaded or self._ip_adapter_dual_loaded:
            self._unload_ip_adapter_safe()

        if self._inpaint_pipe is None:
            print("[MM] Impossible de charger IP-Adapter Style: pas de pipeline")
            return

        print("[MM] Loading IP-Adapter SDXL (CLIP ViT-H style)...")
        try:
            # Standard IP-Adapter (pas Plus) — projection simple, pas de Perceiver resampler
            # ViT-H encoder dans models/image_encoder (1280 dim)
            self._inpaint_pipe.load_ip_adapter(
                "h94/IP-Adapter",
                subfolder="sdxl_models",
                weight_name="ip-adapter_sdxl_vit-h.safetensors",
                image_encoder_folder="models/image_encoder",
            )
            self._ip_adapter_style_loaded = True
            print("[MM] Ready: IP-Adapter SDXL (CLIP ViT-H style)")
        except Exception as e:
            print(f"[MM] IP-Adapter Style error: {e}")
            self._ip_adapter_style_loaded = False

    def _load_ip_adapter_dual(self):
        """Charge les 2 IP-Adapters simultanément (FaceID + Style CLIP)."""
        if self._ip_adapter_dual_loaded:
            return

        # Décharger tout IP-Adapter existant d'abord
        if self._ip_adapter_loaded or self._ip_adapter_style_loaded:
            self._unload_ip_adapter_safe()

        if self._inpaint_pipe is None:
            print("[MM] Impossible de charger IP-Adapter Dual: pas de pipeline")
            return

        # Installer insightface si nécessaire (pour FaceID)
        if not self._ensure_insightface():
            # Fallback: charger seulement le style
            print("[MM] insightface indisponible, fallback style seul")
            self._load_ip_adapter_style()
            return

        print("[MM] Loading IP-Adapter Dual (Style CLIP + FaceID)...")
        try:
            # FaceID repo n'a pas la structure standard → pré-charger comme dict
            # IMPORTANT: Style (repo) DOIT être en premier pour que diffusers charge
            # l'image_encoder depuis le repo (impossible depuis un dict)
            # Ordre: [0]=Style CLIP, [1]=FaceID → ip_adapter_image_embeds=[style, face]
            from huggingface_hub import hf_hub_download
            faceid_path = hf_hub_download(
                "h94/IP-Adapter-FaceID",
                filename="ip-adapter-faceid_sdxl.bin",
            )
            faceid_sd = torch.load(faceid_path, map_location="cpu", weights_only=False)

            self._inpaint_pipe.load_ip_adapter(
                ["h94/IP-Adapter", faceid_sd],
                subfolder=["sdxl_models", None],
                weight_name=["ip-adapter_sdxl_vit-h.safetensors", None],
                image_encoder_folder="models/image_encoder",
            )
            self._ip_adapter_dual_loaded = True
            print("[MM] Ready: IP-Adapter Dual (Style[0] + FaceID[1])")
        except Exception as e:
            print(f"[MM] IP-Adapter Dual error: {e}")
            import traceback
            traceback.print_exc()
            self._ip_adapter_dual_loaded = False

    def _unload_ip_adapter_safe(self):
        """Décharge IP-Adapter en préservant les hooks d'offload.

        unload_ip_adapter() casse les hooks model_cpu_offload/group_offload,
        ce qui laisse le UNet sur CPU → crash "HalfTensor vs cuda.HalfTensor".
        On re-enable l'offload après le unload pour restaurer les hooks.
        """
        if not (self._ip_adapter_loaded or self._ip_adapter_style_loaded or self._ip_adapter_dual_loaded):
            return
        if self._inpaint_pipe is None:
            return
        try:
            self._inpaint_pipe.unload_ip_adapter()
            print("[MM] IP-Adapter déchargé (pas nécessaire pour cette génération)")
            # Re-enable offload hooks (unload_ip_adapter les casse)
            from core.models.gpu_profile import get_offload_strategy
            if get_offload_strategy('sdxl') != "none":
                self._inpaint_pipe.enable_model_cpu_offload()
                print("[MM] Offload hooks ré-activés après déchargement IP-Adapter")
        except Exception as e:
            print(f"[MM] Erreur déchargement IP-Adapter: {e}")
        self._ip_adapter_loaded = False
        self._ip_adapter_style_loaded = False
        self._ip_adapter_dual_loaded = False

    def extract_face_embedding(self, image):
        """Extrait le face embedding via InsightFace pour IP-Adapter FaceID."""
        import numpy as np
        import cv2

        # Bail early si insightface déjà marqué indisponible
        if type(self)._insightface_checked and not type(self)._insightface_available:
            print("[MM] IP-Adapter: insightface indisponible (skip)")
            return None

        try:
            if self._face_analyzer is None:
                from insightface.app import FaceAnalysis
                self._face_analyzer = FaceAnalysis(
                    name="buffalo_l",
                    providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
                )
                self._face_analyzer.prepare(ctx_id=0, det_size=(640, 640))

            # PIL → cv2 BGR
            if hasattr(image, 'mode'):
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                image_cv2 = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            else:
                image_cv2 = image

            faces = self._face_analyzer.get(image_cv2)
            if not faces:
                print("[MM] IP-Adapter: aucun visage détecté")
                return None

            def _face_rank(face):
                bbox = getattr(face, "bbox", None)
                if bbox is None:
                    area = 0.0
                else:
                    x1, y1, x2, y2 = bbox
                    area = max(0.0, float(x2 - x1)) * max(0.0, float(y2 - y1))
                score = float(getattr(face, "det_score", 0.0) or 0.0)
                return area * max(score, 0.01)

            selected_face = max(faces, key=_face_rank)
            if len(faces) > 1:
                print(f"[MM] IP-Adapter: {len(faces)} visages détectés, meilleur visage utilisé")
            selected_score = float(getattr(selected_face, "det_score", 0.0) or 0.0)
            if selected_score < 0.45:
                print(f"[MM] IP-Adapter: visage trop incertain (score={selected_score:.2f}), ignoré")
                return None

            # Embedding normalisé [1, 1, 512]
            faceid_embed = torch.from_numpy(selected_face.normed_embedding).unsqueeze(0)
            ref_embeds = faceid_embed.unsqueeze(0)  # [1, 1, 512]
            neg_embeds = torch.zeros_like(ref_embeds)
            # Utiliser le dtype du pipeline (bf16 sur high-end, fp16 sinon)
            pipe_dtype = torch.float16
            if self._inpaint_pipe is not None and hasattr(self._inpaint_pipe, 'unet'):
                pipe_dtype = self._inpaint_pipe.unet.dtype
            id_embeds = torch.cat([neg_embeds, ref_embeds]).to(dtype=pipe_dtype, device="cuda")
            bbox = getattr(selected_face, "bbox", None)
            if bbox is not None:
                x1, y1, x2, y2 = bbox
                area_pct = (
                    max(0.0, float(x2 - x1))
                    * max(0.0, float(y2 - y1))
                    / max(1.0, float(image_cv2.shape[0] * image_cv2.shape[1]))
                )
                print(
                    f"[MM] IP-Adapter: face embedding extrait "
                    f"(score={selected_score:.2f}, face={area_pct:.1%})"
                )
            else:
                print(f"[MM] IP-Adapter: face embedding extrait (score={selected_score:.2f})")
            return id_embeds

        except Exception as e:
            print(f"[MM] IP-Adapter face embedding error: {e}")
            return None

    def extract_style_embedding(self, image):
        """Extrait le CLIP embedding pour IP-Adapter style (pose, corps, ambiance).

        Utilisé en mode dual (face+style) pour pré-calculer les embeddings style.
        En mode style seul, diffusers encode l'image PIL en interne via ip_adapter_image.
        """
        try:
            pipe = self._inpaint_pipe
            if pipe is None:
                print("[MM] IP-Adapter Style: pas de pipeline")
                return None

            # Le image_encoder et feature_extractor sont chargés par load_ip_adapter
            feature_extractor = pipe.feature_extractor
            image_encoder = pipe.image_encoder

            if feature_extractor is None or image_encoder is None:
                print("[MM] IP-Adapter Style: image_encoder ou feature_extractor manquant")
                return None

            if hasattr(image, 'mode') and image.mode != 'RGB':
                image = image.convert('RGB')

            clip_image = feature_extractor(images=image, return_tensors="pt").pixel_values
            clip_image = clip_image.to(device="cuda", dtype=torch.float16)

            # Déplacer l'encoder sur CUDA si nécessaire (model_cpu_offload le laisse sur CPU)
            encoder_device = next(image_encoder.parameters()).device
            if encoder_device.type == "cpu":
                image_encoder.to(device="cuda", dtype=torch.float16)

            with torch.no_grad():
                # Standard adapter (non-Plus) utilise le pooled output CLIP
                image_embeds = image_encoder(clip_image).image_embeds  # [1, 1280]

            # Remettre l'encoder sur CPU pour libérer la VRAM
            if encoder_device.type == "cpu":
                image_encoder.to("cpu")
                torch.cuda.empty_cache()

            neg_embeds = torch.zeros_like(image_embeds)
            result = torch.cat([neg_embeds, image_embeds])  # [2, 1280]
            print(f"[MM] IP-Adapter Style: CLIP embedding extrait (shape={list(result.shape)})")
            return result

        except Exception as e:
            print(f"[MM] IP-Adapter style embedding error: {e}")
            import traceback
            traceback.print_exc()
            return None

    _depth_cache_hash = None
    _depth_cache_result = None

    def extract_depth(self, image):
        """Extrait une depth map RGB d'une image via Depth Anything V2."""
        if self._depth_estimator is None or self._depth_processor is None:
            self._load_depth_estimator()

        if self._depth_estimator is None:
            print("[MM] Depth estimator unavailable")
            return None

        import numpy as np
        import hashlib
        from PIL import Image as PILImage

        try:
            # Depth Anything V2 attend du RGB, pas RGBA
            if hasattr(image, 'mode') and image.mode != 'RGB':
                image = image.convert('RGB')

            # Cache: même image → même depth map
            _thumb = image.copy()
            _thumb.thumbnail((16, 16), PILImage.BILINEAR)
            _hash = hashlib.md5(_thumb.tobytes()).hexdigest()
            if _hash == type(self)._depth_cache_hash and type(self)._depth_cache_result is not None:
                print(f"[MM] Depth cache hit → skip extraction")
                return type(self)._depth_cache_result.copy()

            device = next(self._depth_estimator.parameters()).device
            inputs = self._depth_processor(images=image, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self._depth_estimator(**inputs)
                depth = outputs.predicted_depth  # (1, H, W)

            # Interpoler à la taille originale
            depth = torch.nn.functional.interpolate(
                depth.unsqueeze(0),
                size=image.size[::-1],  # (H, W)
                mode="bicubic",
                align_corners=False,
            ).squeeze()

            # Normaliser en [0, 255] et convertir en RGB
            depth_np = depth.cpu().numpy()
            depth_np = (depth_np - depth_np.min()) / (depth_np.max() - depth_np.min() + 1e-8) * 255
            depth_rgb = np.stack([depth_np] * 3, axis=-1).astype(np.uint8)
            _result = PILImage.fromarray(depth_rgb)
            type(self)._depth_cache_hash = _hash
            type(self)._depth_cache_result = _result.copy()
            print(f"[MM] Depth map extracted ({image.size[0]}x{image.size[1]})")
            return _result

        except Exception as e:
            print(f"[MM] Depth extraction error: {e}")
            return None


