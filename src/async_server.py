import asyncio
import sys


# --------------------------------------------------
# Running program registry
# --------------------------------------------------

running_tasks = {}


# --------------------------------------------------
# Program management
# --------------------------------------------------

def is_running(program):

    return program in running_tasks


async def start_program(program):

    if is_running(program):
        return program + " is already running."

    module_name = program

    if module_name.endswith(".py"):
        module_name = module_name[:-3]

    try:

        # Remove cached copy so an edited script
        # will be loaded again next time.
        if module_name in sys.modules:
            del sys.modules[module_name]

        module = __import__(module_name)

        if not hasattr(module, "main"):
            return (
                program
                + " does not contain async def main()"
            )

        task = asyncio.create_task(
            module.main()
        )

        running_tasks[program] = task

        print("Started:", program)

        return "Started " + program

    except Exception as e:

        return (
            "Could not start "
            + program
            + ": "
            + str(e)
        )


async def stop_program(program):

    if not is_running(program):

        return program + " is not running."

    task = running_tasks[program]

    task.cancel()

    try:
        await task

    except asyncio.CancelledError:
        pass

    except Exception as e:
        print(
            "Error while stopping",
            program,
            ":",
            e
        )

    del running_tasks[program]

    print("Stopped:", program)

    return "Stopped " + program


# --------------------------------------------------
# HTML
# --------------------------------------------------

def make_page(message=""):

    programs = [
        "torches.py",
        "windmill.py"
    ]

    rows = ""

    for program in programs:

        if is_running(program):

            state = "RUNNING"

            button = """
            <button
                name="action"
                value="stop:%s"
            >
                Stop
            </button>
            """ % program

        else:

            state = "STOPPED"

            button = """
            <button
                name="action"
                value="run:%s"
            >
                Run
            </button>
            """ % program


        rows += """
        <tr>
            <td>%s</td>
            <td>%s</td>
            <td>%s</td>
        </tr>
        """ % (
            program,
            state,
            button
        )


    page = """<!DOCTYPE html>

<html>

<head>

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>ESP32 Task Manager</title>

<style>

body {
    font-family: Arial, sans-serif;
    margin: 20px;
}

table {
    border-collapse: collapse;
    width: 100%%;
    max-width: 650px;
}

td,
th {
    border-bottom: 1px solid #ccc;
    padding: 12px;
    text-align: left;
}

button {
    font-size: 18px;
    padding: 8px 18px;
}

.status {
    margin-top: 25px;
    padding: 12px;
    background: #eeeeee;
}

</style>

</head>


<body>

<h1>LEGO Program Manager</h1>


<form method="POST">

<table>

<tr>
    <th>Program</th>
    <th>Status</th>
    <th>Control</th>
</tr>

%s

</table>

</form>


<div class="status">

<strong>Status:</strong><br>

%s

</div>


</body>

</html>
""" % (
        rows,
        message
    )

    return page


# --------------------------------------------------
# URL decoder
# --------------------------------------------------

def url_decode(text):

    text = text.replace("+", " ")

    result = bytearray()

    i = 0

    while i < len(text):

        if (
            text[i] == "%"
            and i + 2 < len(text)
        ):

            try:

                result.append(
                    int(
                        text[i + 1:i + 3],
                        16
                    )
                )

                i += 3
                continue

            except ValueError:
                pass


        for b in text[i].encode():
            result.append(b)

        i += 1


    return result.decode()


# --------------------------------------------------
# Read HTTP request
# --------------------------------------------------

async def read_request(reader):

    request_line = await reader.readline()

    if not request_line:
        return "", ""

    request_line = request_line.decode().strip()

    content_length = 0


    while True:

        line = await reader.readline()

        if not line:
            break

        if line == b"\r\n":
            break

        text = line.decode().strip()

        if text.lower().startswith(
            "content-length:"
        ):

            content_length = int(
                text.split(":", 1)[1].strip()
            )


    body = ""

    if content_length:

        data = await reader.readexactly(
            content_length
        )

        body = data.decode()


    return request_line, body


# --------------------------------------------------
# Handle browser connection
# --------------------------------------------------

async def handle_client(
    reader,
    writer
):

    message = ""

    try:

        request_line, body = (
            await read_request(reader)
        )


        if request_line.startswith("POST"):

            parts = body.split("&")

            for part in parts:

                if part.startswith(
                    "action="
                ):

                    action = url_decode(
                        part.split(
                            "=",
                            1
                        )[1]
                    )


                    if action.startswith(
                        "run:"
                    ):

                        program = action[4:]

                        message = (
                            await start_program(
                                program
                            )
                        )


                    elif action.startswith(
                        "stop:"
                    ):

                        program = action[5:]

                        message = (
                            await stop_program(
                                program
                            )
                        )


        page = make_page(message)

        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html\r\n"
            "Connection: close\r\n"
            "\r\n"
            + page
        )


        writer.write(
            response.encode()
        )

        await writer.drain()


    except Exception as e:

        print(
            "HTTP error:",
            e
        )


    finally:

        try:
            writer.close()
            await writer.wait_closed()

        except:
            pass


# --------------------------------------------------
# Main
# --------------------------------------------------

async def main():

    print()
    print("ESP32 LEGO Task Manager")
    print("-----------------------")

    server = await asyncio.start_server(
        handle_client,
        "0.0.0.0",
        80
    )

    print(
        "Web server listening on port 80"
    )

    print(
        "Open the ESP32 IP address in Safari."
    )

    # Keep main alive forever while asyncio
    # services the server and LEGO programs.

    while True:
        await asyncio.sleep(3600)


asyncio.run(main())