import psycopg2
import os

def app(environ, start_response):
    connstring = os.environ['CONNSTRING']
    conn = psycopg2.connect(connstring)
    cur = conn.cursor()
    cur.execute("SELECT * FROM mtm;")
    rows = cur.fetchall()
    data = b""
    for row in rows:
        data += (str(row) + "\n").encode()
    cur.close()
    conn.close()

    start_response("200 OK", [
        ("Content-Type", "text/plain"),
        ("Content-Length", str(len(data)))
    ])
    return iter([data])
