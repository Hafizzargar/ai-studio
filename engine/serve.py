"""Start the local UI: python -m engine.serve  (then open http://127.0.0.1:8765)"""
import threading
import webbrowser

from aistudio.server import run

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    run()
