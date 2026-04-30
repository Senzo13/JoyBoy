# Cloud / Remote GPU Setup

Use this guide when JoyBoy runs on a remote GPU machine such as Lambda, RunPod, Vast.ai, or a self-managed Linux box.

## 1. Connect to the remote GPU

Most cloud GPU providers give you:

- a public IP address
- a Linux user, often `ubuntu`
- an SSH key name or SSH private key
- a region and instance type

Never commit a real IP address, SSH key, token, or provider-specific account URL to the repo.

### Lambda Cloud

Lambda Cloud instances usually show an SSH command like:

```text
ssh ubuntu@<PUBLIC_IP>
```

Use an SSH tunnel so JoyBoy stays bound to `127.0.0.1` on the remote machine while your local browser can open it safely.

#### Windows PowerShell

```powershell
ssh -i "$env:USERPROFILE\.ssh\<KEY_NAME>" -L 7860:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

If you are not sure where your key is:

```powershell
ls "$env:USERPROFILE\.ssh"
```

#### macOS / Linux

```bash
chmod 600 ~/.ssh/<KEY_NAME>
ssh -i ~/.ssh/<KEY_NAME> -L 7860:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

If your SSH config already knows the key, this is enough:

```bash
ssh -L 7860:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

Keep the SSH session open while JoyBoy is running. On your local machine, open:

```text
http://127.0.0.1:7860
```

If JoyBoy is already running in another SSH terminal and you only need access from your own computer, open a second local terminal and create the tunnel without opening an interactive shell:

#### Windows PowerShell

```powershell
ssh -i "$env:USERPROFILE\.ssh\<KEY_NAME>" -N -L 7860:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

#### macOS / Linux

```bash
ssh -i ~/.ssh/<KEY_NAME> -N -L 7860:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

Keep that tunnel terminal open, then browse locally to:

```text
http://127.0.0.1:7860
```

If port `7860` is already used on your own computer, map a different local port while keeping JoyBoy remote on `7860`:

```powershell
ssh -i "$env:USERPROFILE\.ssh\<KEY_NAME>" -N -L 7861:127.0.0.1:7860 ubuntu@<PUBLIC_IP>
```

Then open:

```text
http://127.0.0.1:7861
```

Important: the URL printed by JoyBoy, `http://127.0.0.1:7860`, is local to the machine where JoyBoy is running. On a cloud GPU, that means the remote server. Your personal computer can only use that URL after the SSH tunnel is active.

## 2. Clone the project

```bash
cd ~
git clone <YOUR_REPOSITORY_URL>
cd JoyBoy
```

Do not hardcode tokens in the clone URL.

For the public JoyBoy repository:

```bash
git clone https://github.com/Senzo13/JoyBoy.git
cd JoyBoy
```

## 3. Configure providers

You have two safe options:

### Option A: local `.env`

```bash
cp .env.example .env
```

Then edit `.env` with your own values:

```bash
HF_TOKEN=hf_your_token_here
CIVITAI_API_KEY=your_civitai_key_here
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

### Option B: JoyBoy UI

Start JoyBoy once, open `Settings > Models`, and save provider secrets there.

UI-managed secrets are stored locally in `~/.joyboy/config.json` and stay out of git.

## 4. Install and start JoyBoy

### Linux launcher

```bash
chmod +x start_linux.sh
./start_linux.sh
```

### Manual fallback

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 web/app.py
```

JoyBoy listens on:

```text
http://127.0.0.1:7860
```

If you connected with `-L 7860:127.0.0.1:7860`, open the same URL on your local computer.

## 5. Access JoyBoy from another machine

### SSH tunnel

```bash
ssh -L 7860:127.0.0.1:7860 <REMOTE_USER>@<PUBLIC_IP>
```

Then open:

```text
http://127.0.0.1:7860
```

### Cloudflare Tunnel

If you already use `cloudflared`, you can expose the local port through your own tunnel workflow. Keep the public endpoint private and temporary unless you know exactly what you are exposing.

## 6. Recommended first checks

After startup:

1. open JoyBoy
2. complete onboarding
3. open `Settings > Models`
4. run the Doctor
5. verify providers and disk paths

## 7. Troubleshooting

### Permission denied (publickey)

Confirm the key path and user:

```bash
ssh -i ~/.ssh/<KEY_NAME> ubuntu@<PUBLIC_IP>
```

On Windows PowerShell:

```powershell
ssh -i "$env:USERPROFILE\.ssh\<KEY_NAME>" ubuntu@<PUBLIC_IP>
```

If Lambda generated the SSH command, prefer the exact user shown by Lambda, then add the `-L 7860:127.0.0.1:7860` tunnel.

### Ollama not reachable

Set or override:

```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
```

### CUDA out of memory

- use the Doctor report to confirm GPU memory
- prefer lighter default models
- unload unused models from the UI

### Provider download fails

- verify the provider key in `Settings > Models`
- confirm the source URL is public or that the key grants access

### Port already in use

```bash
lsof -i :7860
```

Then stop the conflicting process.
