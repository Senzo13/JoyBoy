"""
Interface Gradio
3 vues separees: Home, Chat, Modal
"""
import gradio as gr
from PIL import Image
from pathlib import Path
import base64
from io import BytesIO
import sys
import os

# Import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config import AI_NAME
except ImportError:
    AI_NAME = "JoyBoy"

from ui.styles import DARK_THEME_CSS, PASTE_JS, ICONS
from core.models import MODELS
from core.processing import process_image, generate_video, upscale_image, expand_image

# State global
class AppState:
    original_image = None
    modified_image = None
    uploaded_image = None
    current_prompt = ""
    selected_image = "modified"

state = AppState()


def image_to_base64_thumb(img, size=50):
    if img is None:
        return ""
    thumb = img.copy()
    thumb.thumbnail((size, size))
    buf = BytesIO()
    thumb.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def create_interface():
    with gr.Blocks(css=DARK_THEME_CSS, theme=gr.themes.Base().set(
        body_background_fill="#000",
        body_background_fill_dark="#000",
        block_background_fill="#000",
        block_background_fill_dark="#000",
    )) as app:

        # JS pour Ctrl+V
        gr.HTML(PASTE_JS)

        # State pour l'image
        current_image = gr.State(None)

        # Tabs pour les 3 vues (onglets caches via CSS)
        with gr.Tabs(elem_classes=["hidden-tabs"]) as tabs:

            # ===== TAB 1: HOME =====
            with gr.Tab("home", id=0, elem_classes=["tab-home"]):
                gr.HTML(f'<div class="logo-container"><span class="logo-text">{AI_NAME}</span></div>')

                with gr.Row(elem_classes=["unified-input-bar"]):
                    attach_btn = gr.UploadButton(
                        ICONS['attach'],
                        file_types=["image"],
                        elem_classes=["attach-btn"],
                        scale=0, min_width=40
                    )
                    image_thumb = gr.HTML("", elem_classes=["image-thumb-indicator"])
                    prompt_home = gr.Textbox(
                        placeholder="Que voulez-vous modifier ?",
                        show_label=False, container=False,
                        elem_classes=["main-prompt-input"],
                        scale=1,
                        interactive=True
                    )
                    model_select = gr.Dropdown(
                        choices=["🚀 Automatique"] + list(MODELS.keys()),
                        value="🚀 Automatique",
                        show_label=False,
                        elem_classes=["model-select"],
                        scale=0, min_width=160,
                        interactive=True,
                        allow_custom_value=False
                    )
                    send_home = gr.Button(ICONS['send'], elem_classes=["send-btn-round"], scale=0, min_width=40)

                # Status de chargement
                loading_status = gr.HTML("", elem_classes=["loading-status"])

            # ===== TAB 2: CHAT =====
            with gr.Tab("chat", id=1, elem_classes=["tab-chat"]):
                with gr.Row(elem_classes=["chat-header"]):
                    back_btn = gr.Button(ICONS['back'], elem_classes=["back-btn"], scale=0, min_width=44)
                    gr.HTML("<div style='flex:1'></div>")
                    share_chat = gr.Button(f"{ICONS['share']} Partager", elem_classes=["share-btn"], scale=0)

                # Zone de conversation scrollable
                with gr.Column(elem_classes=["chat-messages"]):
                    # Message utilisateur (a droite)
                    user_msg = gr.HTML("", elem_classes=["user-msg"])

                    # Reponse IA avec images (en dessous)
                    with gr.Row(elem_classes=["images-row"]):
                        img_original = gr.Image(show_label=False, interactive=False, elem_classes=["result-img"], label="Original")
                        with gr.Column(elem_classes=["img-col-right"]):
                            img_modified = gr.Image(show_label=False, interactive=False, elem_classes=["result-img"], label="Modifie")
                            expand_btn = gr.Button(ICONS['expand'], elem_classes=["expand-btn"], scale=0, min_width=40)

                # Input en bas fixe
                with gr.Row(elem_classes=["chat-input-row"]):
                    with gr.Row(elem_classes=["unified-input-bar", "chat-bar"]):
                        prompt_chat = gr.Textbox(
                            placeholder="Continuer la conversation...",
                            show_label=False, container=False,
                            elem_classes=["main-prompt-input"], scale=3,
                            interactive=True
                        )
                        send_chat = gr.Button(ICONS['send'], elem_classes=["send-btn-round"], scale=0, min_width=44)

            # ===== TAB 3: MODAL =====
            with gr.Tab("modal", id=2, elem_classes=["tab-modal"]):
                with gr.Row(elem_classes=["modal-header"]):
                    download_btn = gr.Button(ICONS['download'], elem_classes=["modal-btn"], scale=0, min_width=44)
                    gr.HTML("<div style='flex:1'></div>")
                    share_modal = gr.Button(f"{ICONS['share']} Partager", elem_classes=["share-btn"], scale=0)
                    close_btn = gr.Button(ICONS['close'], elem_classes=["close-btn"], scale=0, min_width=44)

                with gr.Row(elem_classes=["modal-body"]):
                    with gr.Column(scale=4, elem_classes=["modal-main"]):
                        modal_img = gr.Image(show_label=False, interactive=False, elem_classes=["modal-main-img"])
                    with gr.Column(scale=1, elem_classes=["modal-side"]):
                        thumb_orig = gr.Image(show_label=False, interactive=False, height=80, elem_classes=["modal-thumb"])
                        btn_orig = gr.Button("Original", size="sm", elem_classes=["thumb-label"])
                        thumb_mod = gr.Image(show_label=False, interactive=False, height=80, elem_classes=["modal-thumb", "selected"])
                        btn_mod = gr.Button("Modifie", size="sm", elem_classes=["thumb-label"])

                with gr.Row(elem_classes=["modal-actions"]):
                    btn_upscale = gr.Button(f"{ICONS['upscale']} Upscale x2", elem_classes=["action-pill"])
                    btn_expand = gr.Button(f"{ICONS['expand']} Agrandir", elem_classes=["action-pill"])
                    btn_video = gr.Button(f"{ICONS['play']} Creer video", elem_classes=["action-pill"])
                    btn_creative = gr.Button(f"{ICONS['sparkle']} Creatif", elem_classes=["action-pill"])
                    btn_bg = gr.Button(f"{ICONS['mountain']} Arriere-plan", elem_classes=["action-pill"])
                    btn_subject = gr.Button(f"{ICONS['user']} Sujet", elem_classes=["action-pill"])

                with gr.Row(elem_classes=["modal-input-row"]):
                    with gr.Column(scale=1):
                        pass
                    with gr.Column(scale=2):
                        with gr.Row(elem_classes=["unified-input-bar"]):
                            prompt_modal = gr.Textbox(
                                placeholder="Decrivez vos modifications...",
                                show_label=False, container=False,
                                elem_classes=["main-prompt-input"], scale=3,
                                interactive=True
                            )
                            send_modal = gr.Button(ICONS['send'], elem_classes=["send-btn-round"], scale=0, min_width=44)
                    with gr.Column(scale=1):
                        pass

        # ===== EVENTS =====

        # Upload image
        def on_upload(file, img_state):
            if file:
                img = Image.open(file.name)
                state.uploaded_image = img
                b64 = image_to_base64_thumb(img, 36)
                return img, f'<img src="data:image/png;base64,{b64}" class="thumb-img"/>'
            return img_state, ""

        attach_btn.upload(on_upload, [attach_btn, current_image], [current_image, image_thumb])

        # Generate depuis Home -> Chat
        def generate_home(img, prompt, model):
            print(f"[DEBUG] generate_home called")
            print(f"[DEBUG] img: {type(img)}, prompt: '{prompt}', model: '{model}'")

            if img is None:
                print("[DEBUG] No image!")
                gr.Warning("Colle une image (Ctrl+V) ou clique sur 📎")
                return gr.Tabs(selected=0), "", None, None, ""
            if not prompt.strip():
                print("[DEBUG] No prompt!")
                gr.Warning("Ecris ce que tu veux modifier")
                return gr.Tabs(selected=0), "", None, None, ""

            print("[DEBUG] Processing image...")

            try:
                result, original, status = process_image(img, prompt, 0.6, model)
                print(f"[DEBUG] Result: {result is not None}, Status: {status}")

                if result:
                    state.original_image = original
                    state.modified_image = result
                    state.current_prompt = prompt
                    b64 = image_to_base64_thumb(img, 50)
                    html = f'''<div class="user-bubble">
                        <div class="bubble-text">{prompt}</div>
                        <img src="data:image/png;base64,{b64}" class="bubble-thumb"/>
                    </div>'''
                    return gr.Tabs(selected=1), html, original, result, ""

                gr.Warning(status)
                return gr.Tabs(selected=0), "", None, None, ""
            except Exception as e:
                print(f"[ERROR] {e}")
                import traceback
                traceback.print_exc()
                gr.Warning(f"Erreur: {e}")
                return gr.Tabs(selected=0), "", None, None, f'<span style="color:red">Erreur: {e}</span>'

        def show_loading():
            return '<div class="loading-spinner">Generation en cours...</div>'

        # Au clic: afficher loading puis generer
        send_home.click(
            show_loading, None, loading_status
        ).then(
            generate_home,
            [current_image, prompt_home, model_select],
            [tabs, user_msg, img_original, img_modified, loading_status]
        )
        prompt_home.submit(
            show_loading, None, loading_status
        ).then(
            generate_home,
            [current_image, prompt_home, model_select],
            [tabs, user_msg, img_original, img_modified, loading_status]
        )

        # Back to Home
        back_btn.click(lambda: gr.Tabs(selected=0), None, tabs)

        # Expand -> Modal
        def open_modal():
            return gr.Tabs(selected=2), state.modified_image, state.original_image, state.modified_image

        expand_btn.click(open_modal, None, [tabs, modal_img, thumb_orig, thumb_mod])

        # Close Modal -> Chat
        close_btn.click(lambda: gr.Tabs(selected=1), None, tabs)

        # Thumbs selection
        def sel_orig():
            state.selected_image = "original"
            return state.original_image

        def sel_mod():
            state.selected_image = "modified"
            return state.modified_image

        btn_orig.click(sel_orig, None, modal_img)
        btn_mod.click(sel_mod, None, modal_img)

        # Regenerate from Chat
        def regen_chat(prompt, model):
            if not prompt.strip():
                prompt = state.current_prompt
            result, _, status = process_image(state.original_image, prompt, 0.6, model)
            if result:
                state.modified_image = result
                return result
            return state.modified_image

        send_chat.click(regen_chat, [prompt_chat, model_select], img_modified)

        # Generate from Modal
        def gen_modal(prompt, model):
            if not prompt.strip():
                return state.modified_image
            result, _, _ = process_image(state.original_image, prompt, 0.6, model)
            if result:
                state.modified_image = result
                return result
            return state.modified_image

        send_modal.click(gen_modal, [prompt_modal, model_select], modal_img)

        # Video
        def make_video():
            img = state.modified_image if state.selected_image == "modified" else state.original_image
            video_data, _, status = generate_video(img)
            gr.Info(f"Video générée! ({status})")

        btn_video.click(make_video, None, None)

        # Upscale x2
        def do_upscale():
            img = state.modified_image if state.selected_image == "modified" else state.original_image
            if img is None:
                gr.Warning("Pas d'image a upscaler")
                return None, None
            gr.Info("Upscaling en cours...")
            result, status = upscale_image(img, scale=2)
            if result:
                state.modified_image = result
                gr.Info(f"Upscale termine! {status}")
                return result, result
            gr.Warning(status)
            return None, None

        btn_upscale.click(do_upscale, None, [modal_img, thumb_mod])

        # Expand (outpainting)
        def do_expand():
            img = state.modified_image if state.selected_image == "modified" else state.original_image
            if img is None:
                gr.Warning("Pas d'image a agrandir")
                return None, None
            gr.Info("Expansion en cours... (peut prendre 30-60 sec)")
            result, status = expand_image(img, ratio=1.5, prompt="")
            if result:
                state.modified_image = result
                gr.Info(f"Expansion terminee! {status}")
                return result, result
            gr.Warning(status)
            return None, None

        btn_expand.click(do_expand, None, [modal_img, thumb_mod])

    return app
