# Gestion VRAM - JoyBoy

Derniere mise a jour: 2026-04-16.

Cette page decrit le comportement actuel du runtime. Elle ne doit pas etre lue
comme une promesse ligne par ligne: JoyBoy garde certains modeles chauds quand
c'est utile, mais libere ce qui entre en conflit avec la tache en cours.

## Principes actuels

| Principe | Comportement |
|---|---|
| Demarrage leger | Aucun gros modele image/video n'est charge au lancement. |
| Load-on-demand | Les pipelines diffusion, video, caption, segmentation et upscale se chargent quand une tache les demande. |
| Pas de hard reset au refresh | Le refresh UI ne lance plus `/models/unload-all`. Les modeles peuvent rester en memoire pour accelerer la suite. |
| Jobs durables | Les generations, imports, downloads et taches terminal sont suivis par `JobManager`, pas par du HTML temporaire. |
| Groupes VRAM | Les taches sont classees en groupes `diffusion`, `video`, `chat` et `io`. |
| Low VRAM strict | Sur 8-10 GB VRAM, JoyBoy decharge Ollama avant les jobs diffusion/video quand il faut eviter la saturation. |
| Reset manuel disponible | Le bouton "Liberer VRAM" et `/models/unload-all` restent des actions explicites de securite. |

## Sources de verite

| Fichier | Role |
|---|---|
| `core/models/manager.py` | Cycle de vie des modeles, smart unload, quantification, chargement diffusion/video/chat. |
| `core/runtime/resources.py` | Plans et leases de ressources visibles dans le panneau runtime. |
| `core/runtime/jobs.py` | Etat durable des jobs, progression, annulation et restauration UI. |
| `web/app.py` | `generation_pipeline()`, integration du scheduler et du `ModelManager`. |
| `web/routes/models.py` | Endpoints unload, warmup Ollama, status et downloads. |
| `web/routes/runtime.py` | API runtime pour jobs, conversations et etat ressources. |
| `web/static/js/ui.js` | Picker de modeles, selection inpaint/text2img/chat selon le contexte. |
| `web/static/js/settings.js` | Cartes modeles, imports CivitAI/Hugging Face, equipement de modeles. |

## Groupes de ressources

`ResourceScheduler` ne remplace pas `ModelManager`: il enregistre les plans et
les leases pour l'UI/runtime. Le vrai chargement/dechargement reste dans
`ModelManager.load_for_task()`.

| Groupe | Taches typiques | Politique |
|---|---|---|
| `diffusion` | inpaint, text2img, edit, expand, upscale | Peut reutiliser un pipeline diffusion deja chaud. Decharge la video. Sur low VRAM, decharge aussi Ollama sauf demande explicite de preservation. |
| `video` | FramePack, SVD, CogVideo, export video | Tache la plus gourmande. Decharge diffusion, utils lourds, segmentation et Ollama sur low VRAM. |
| `chat` | conversation, terminal, caption | Peut tourner tant qu'aucun job diffusion/video lourd ne reclame la VRAM. |
| `io` | download, import modele, import pack | Ne devrait pas bloquer la VRAM sauf si une verification charge un modele. |

## Model Picker

Le picker garde trois familles visibles, mais les listes ne sont plus une simple
liste statique.

| Onglet | Usage | Stockage |
|---|---|---|
| Inpaint | Une image est presente dans l'input ou l'editeur | `selectedInpaintModel` |
| Text2Img | Prompt texte sans image source | `selectedText2ImgModel` |
| Chat | Conversation et mode projet | `userSettings.chatModel` |

`getCurrentImageModel()` choisit le modele image selon la presence d'une image.
Les modeles viennent de plusieurs sources:

- catalogues integres;
- modeles installes;
- imports Hugging Face ou CivitAI;
- packs locaux actives;
- variantes runtime comme INT4, INT8, FP16, FP8 ou GGUF quand disponibles.

Pour les imports CivitAI/Hugging Face, un checkpoint source peut rester FP16
sur disque tout en etant execute en INT8 au chargement si le profil local le
demande et si la quantification reussit.

## Demarrage et refresh

Ancien comportement: refresh = `/models/unload-all` puis warmup utility + chat.

Comportement actuel:

1. L'UI demarre vite.
2. JoyBoy verifie si une generation video est deja active et se reconnecte si besoin.
3. Le refresh ne decharge plus les modeles par defaut.
4. Les conversations et jobs sont reconstruits depuis le runtime store.
5. L'onboarding/Doctor se lance sans bloquer l'affichage initial.
6. Le warmup Ollama est fait a la demande par le chat, le terminal ou les outils.

Ce changement evite les cycles inutiles `load -> unload -> reload` apres chaque
refresh, surtout quand un modele image vient d'etre charge.

## Changement de modele

| Action | Comportement actuel |
|---|---|
| Equiper un modele inpaint | Sauvegarde `selectedInpaintModel`, reset le flag de chargement local, notifie `/api/log/model-change`. |
| Equiper un modele text2img | Sauvegarde `selectedText2ImgModel`, reset le flag local, charge a la prochaine generation. |
| Equiper un modele chat | Sauvegarde `userSettings.chatModel`; Ollama peut etre warmup ensuite selon le contexte. |
| `/api/log/model-change` | Log uniquement. Ne preload plus et ne decharge plus automatiquement. |
| `/models/preload-image` | No-op volontaire: les modeles image sont load-on-demand. |

Le changement de modele ne doit donc plus etre documente comme un unload
obligatoire. L'ancien pipeline est decharge quand `ModelManager` detecte qu'un
autre modele doit vraiment etre charge, ou quand l'utilisateur libere la VRAM.

## Generation image

Flux simplifie:

1. La route cree ou met a jour un job.
2. `generation_pipeline()` ouvre un lease de ressources.
3. `ModelManager.load_for_task()` charge uniquement ce qui manque.
4. Sur low VRAM, Ollama est decharge avant diffusion si sa presence risque de bloquer SDXL/ControlNet.
5. Les previews et la progression mettent a jour le job actif.
6. `cleanup()` libere surtout les utilitaires temporaires; il ne fait pas un reset complet.

Pour l'inpainting, JoyBoy essaie de garder le pipeline diffusion chaud quand il
est probable que l'utilisateur enchaine plusieurs edits. Pour text2img, le
modele peut aussi rester chaud selon l'etat courant, la pression VRAM et les
actions utilisateur. Il ne faut plus affirmer "text2img est toujours decharge
apres generation".

## Generation video

La video est traitee comme le groupe le plus gourmand.

| Phase | Politique |
|---|---|
| Avant video | Decharger diffusion, segmentation lourde, utils et Ollama si la VRAM est faible. |
| Pendant generation | Garder le modele video comme ressource principale. |
| Low VRAM FramePack | Reduire resolution/steps/frames selon preset et liberer des composants avant le decodage quand possible. |
| Export | Eviter de garder inutilement le modele video si l'export/decode risque de saturer RAM/VRAM. |
| Audio auto | Doit rester optionnel/desactive par defaut sur machines limitees, car MMAudio peut consommer beaucoup de VRAM. |

## Ollama, chat et terminal

| Cas | Comportement |
|---|---|
| Chat normal | Le modele chat peut rester chaud pour repondre vite. |
| Mode projet/terminal | Warmup du modele choisi, puis job terminal cancellable. |
| Image/video sur low VRAM | Ollama est decharge et JoyBoy attend brievement que `/api/ps` confirme la liberation. |
| Warmup pendant generation | `/ollama/warmup` peut refuser/skip si une generation lourde est active. |
| `keep_alive: "0s"` | Demande a Ollama de decharger un modele. |
| `keep_alive: "5m"` ou `-1` | Garde le modele chaud selon le service appele et le contexte. |

## Endpoints utiles

| Endpoint | Role actuel |
|---|---|
| `GET /api/runtime/status` | Etat jobs, conversations, ressources et modeles charges. |
| `GET/POST /api/runtime/jobs` | Creer/lister les jobs durables. |
| `POST /api/runtime/jobs/<id>/cancel` | Demander ou forcer l'annulation d'un job. |
| `POST /models/unload-all` | Reset manuel: annule les generations actives et decharge tout, avec option `keep_video`. |
| `POST /models/unload-image` | Decharge les pipelines image/diffusion. |
| `POST /models/preload-image` | No-op load-on-demand, garde pour compat UI. |
| `POST /ollama/warmup` | Warmup Ollama a la demande, avec protection pendant generation. |
| `POST /api/log/model-change` | Log changement modele, sans preload ni unload automatique. |
| `GET /check-models` | Etat des modeles image connus/installes. |
| `POST /models/download` | Telechargement modele en tache de fond. |

## Transitions resumees

| Evenement | Transition actuelle |
|---|---|
| Refresh UI | Reconnecter jobs/video, charger conversations, ne pas unload par defaut. |
| Chat -> image | Creer job diffusion, liberer Ollama si low VRAM, charger le modele image a la demande. |
| Image -> chat | Le chat peut warmup a la demande; le modele image peut rester chaud jusqu'a pression VRAM ou unload manuel. |
| Image -> autre modele image | Le prochain load remplace le pipeline incompatible; pas de preload automatique. |
| Image/video -> terminal | Le terminal peut warmup Ollama, mais les jobs lourds actifs doivent etre annules/termines ou liberer leurs leases. |
| Suppression conversation | Annule les jobs non terminaux attaches a cette conversation. |
| Liberer VRAM | Hard reset volontaire via `unload_all()`. |

## Regles a garder en tete

1. Ne pas documenter un unload automatique si le code ne l'execute pas.
2. Ne pas supposer un modele utility fixe: le router texte depend de la config et des modeles installes.
3. Sur 8 GB VRAM, eviter de garder Ollama et SDXL/FramePack ensemble.
4. `JobManager` stocke l'etat stable; l'UI reconstruit les skeletons depuis les jobs.
5. Les imports de modeles peuvent etre source FP16 mais runtime INT8.
6. Les actions explicites de l'utilisateur priment: "Liberer VRAM" doit vraiment tout liberer.
7. Les caches legers peuvent rester en RAM/VRAM si le gain de reload ne vaut pas le cout.

## Verification rapide

Commandes utiles apres une modification de cette zone:

```bash
python -m unittest discover -s tests -p "test_*.py"
node --check web/static/js/app.js
node --check web/static/js/ui.js
node --check web/static/js/settings.js
```

Et cote UI:

- ouvrir le panneau VRAM/runtime;
- lancer un chat, puis une generation image sur GPU 8 GB;
- verifier qu'Ollama est libere avant diffusion si la pression VRAM est haute;
- changer de conversation pendant un job et revenir;
- verifier que la carte se reconstruit depuis le job, pas depuis un vieux skeleton DOM.
