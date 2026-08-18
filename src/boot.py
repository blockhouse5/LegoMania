import network
import time
import socket
import machine

HOSTNAME = "legolab"
SETUP_AP_NAME = "LEGO-Lab-Setup"


def load_config():
    try:
        import config
        return config.WIFI_SSID, config.WIFI_PASSWORD
    except Exception as e:
        print("No valid WiFi configuration:", e)
        return None, None


def connect_wifi(ssid, password):
    network.hostname(HOSTNAME)

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        return wlan

    print("Connecting to WiFi:", ssid)
    wlan.connect(ssid, password)

    # Wait up to about 15 seconds
    for _ in range(30):
        if wlan.isconnected():
            break
        time.sleep(0.5)

    if wlan.isconnected():
        print("WiFi connected")
        print("Hostname:", network.hostname())
        print("IP:", wlan.ifconfig()[0])
        return wlan

    print("WiFi connection failed")

    wlan.disconnect()
    wlan.active(False)

    return None


def url_decode(text):
    text = text.replace("+", " ")

    result = ""
    i = 0

    while i < len(text):
        if text[i] == "%" and i + 2 < len(text):
            try:
                result += chr(int(text[i + 1:i + 3], 16))
                i += 3
                continue
            except:
                pass

        result += text[i]
        i += 1

    return result


def get_form_value(body, name):
    for part in body.split("&"):
        if "=" in part:
            key, value = part.split("=", 1)

            if key == name:
                return url_decode(value)

    return ""


def save_config(ssid, password):
    with open("config.py", "w") as f:
        f.write('WIFI_SSID = "{}"\n'.format(
            ssid.replace("\\", "\\\\").replace('"', '\\"')
        ))

        f.write('WIFI_PASSWORD = "{}"\n'.format(
            password.replace("\\", "\\\\").replace('"', '\\"')
        ))

        f.write('\nHOSTNAME = "{}"\n'.format(HOSTNAME))


def setup_page():
    return """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport"
          content="width=device-width, initial-scale=1">

    <title>LEGO Project Lab Setup</title>

    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 500px;
            margin: 40px auto;
            padding: 20px;
        }

        h1 {
            color: #d01012;
        }

        input {
            width: 100%;
            box-sizing: border-box;
            padding: 12px;
            margin: 8px 0 18px 0;
            font-size: 16px;
        }

        button {
            background: #ffd500;
            border: 2px solid #222;
            padding: 12px 20px;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
        }
    </style>
</head>

<body>

<h1>LEGO Project Lab</h1>

<h2>Wi-Fi Setup</h2>

<p>
Enter the Wi-Fi network this Project Lab should use.
</p>

<form method="POST">

<label>Wi-Fi Network</label>
<input
    type="text"
    name="ssid"
    required
>

<label>Wi-Fi Password</label>
<input
    type="password"
    name="password"
>

<button type="submit">
    Save & Connect
</button>

</form>

</body>
</html>
"""


def start_setup_mode():
    print()
    print("Starting LEGO Project Lab setup mode...")

    ap = network.WLAN(network.AP_IF)

    ap.config(
        ssid=SETUP_AP_NAME
    )

    ap.active(True)

    while not ap.active():
        time.sleep(0.1)

    ip = ap.ifconfig()[0]

    print("Setup WiFi:", SETUP_AP_NAME)
    print("Setup address: http://" + ip)

    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]

    server = socket.socket()
    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    server.bind(addr)
    server.listen(1)

    print("Waiting for WiFi setup...")

    while True:

        client, remote_addr = server.accept()

        try:
            request = client.recv(4096).decode()

            if request.startswith("POST "):

                body = ""

                if "\r\n\r\n" in request:
                    body = request.split(
                        "\r\n\r\n",
                        1
                    )[1]

                ssid = get_form_value(
                    body,
                    "ssid"
                )

                password = get_form_value(
                    body,
                    "password"
                )

                if ssid:

                    print("Saving WiFi configuration:", ssid)

                    save_config(
                        ssid,
                        password
                    )

                    response = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<title>Setup Complete</title>
</head>

<body style="font-family:Arial;padding:30px;">

<h1>Setup Complete!</h1>

<p>
LEGO Project Lab is restarting.
</p>

<p>
Reconnect your iPad to your normal Wi-Fi network,
then open:
</p>

<h2>
http://legolab.local
</h2>

</body>
</html>
"""

                    client.send(
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: text/html\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )

                    client.send(response)
                    client.close()

                    time.sleep(2)

                    machine.reset()

                else:
                    client.send(
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                        "Missing WiFi network"
                    )

            else:

                page = setup_page()

                client.send(
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: text/html\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )

                client.send(page)

        except Exception as e:
            print("Setup server error:", e)

        finally:
            try:
                client.close()
            except:
                pass


# --------------------------------------------------
# BOOT
# --------------------------------------------------

ssid, password = load_config()

wlan = None

if ssid:
    wlan = connect_wifi(
        ssid,
        password
    )


if not wlan:

    start_setup_mode()

print("boot.py finished")