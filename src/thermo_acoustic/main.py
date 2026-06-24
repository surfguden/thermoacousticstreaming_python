from __future__ import annotations

from .application import Application
from .messages import Message, MessageName


def main() -> None:
    app = Application()
    app.enqueue_main(Message(MessageName.INITIALIZE))
    app.run_until_idle()
    print(app.status)


if __name__ == "__main__":
    main()

