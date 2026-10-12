# Run Outside Bingo on Arduino UNO Q

Outside Bingo runs on the UNO Q's Qualcomm MPU under Debian Linux. It does not
require an Arduino sketch or use the STM32 MCU, so the MCU remains free for
future sensors, buttons, LEDs, or other real-time work through Arduino Bridge.

## What you need

- An Arduino UNO Q that has completed first-time setup in Arduino App Lab
- Wi-Fi or Ethernet connectivity
- SSH access (or an ADB shell over USB-C)
- Internet access during installation and for live SerpApi/Backboard requests

Use a stable power source. Arduino specifies 5 V / 3 A over USB-C, or a supported
external supply.

## Install over SSH

On your computer, connect to the board. Replace the hostname if you selected a
different one during setup:

```bash
ssh arduino@uno-q.local
```

Then run these commands on the UNO Q:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/im45145v/Boutgo---Outside-Bingo.git
cd Boutgo---Outside-Bingo
./deploy/uno-q/install.sh
```

The installer creates an ARM64 Python virtual environment, installs the app,
registers a `systemd` service, stores SQLite data under
`/var/lib/outside-bingo/`, starts the service, and checks `/health`.

Open the URL printed by the installer, normally:

```text
http://uno-q.local:5000
```

If `.local` discovery is unavailable on your network, get the board's address:

```bash
hostname -I
```

Then open `http://<board-ip>:5000` from a device on the same network.

## Enable live destination search and AI missions

The app works in labelled demo mode without keys. To enable live features:

```bash
APP_DIR="$(systemctl show -p WorkingDirectory --value outside-bingo)"
cd "$APP_DIR"
nano .env
```

Using the service's configured working directory avoids editing the wrong file
if the repository was cloned into a nested directory.

Set `SERPAPI_API_KEY` and `BACKBOARD_API_KEY`, save the file, and restart:

```bash
chmod 600 .env
sudo systemctl restart outside-bingo
until curl --fail http://127.0.0.1:5000/health; do sleep 1; done
```

Do not commit `.env`; it is ignored by Git.

## Operate and troubleshoot

```bash
sudo systemctl status outside-bingo
sudo journalctl -u outside-bingo -f
sudo systemctl restart outside-bingo
sudo systemctl stop outside-bingo
```

Update to the newest version:

```bash
cd ~/Boutgo---Outside-Bingo
git pull --ff-only
./deploy/uno-q/install.sh
```

If `hostname -I` lists several addresses, ignore Docker bridge addresses such
as `172.17.0.1`. Find the LAN address used by the default route with:

```bash
ip -4 route get 1.1.1.1 | awk '{for (i=1; i<=NF; i++) if ($i == "src") print $(i+1)}'
```

If the page is reachable on the board but not another device, confirm both are
on the same non-guest network and that client isolation is disabled. The app
listens on TCP port 5000. Do not expose that port directly to the public
internet; use a VPN such as Tailscale or a properly configured reverse proxy.

## ADB alternative

With the UNO Q connected over USB-C and ADB installed on the computer:

```bash
adb devices
adb shell
```

Run the same clone and installer commands inside that shell. The final web page
still uses the board's network address; ADB is only the management connection.

