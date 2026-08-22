import argparse
import asyncio

from rich.console import Console
from rich.prompt import Prompt

from core.accounts import interactive_add_account


console = Console()


def interactive_cli():
    console.print("[bold green]Welcome to QQ SparkFlow[/bold green]")
    console.print("[bold yellow]Choose an action:[/bold yellow]")
    console.print("[cyan]1.[/cyan] Add QQ account")
    console.print("[cyan]2.[/cyan] Run task immediately")
    console.print("[cyan]3.[/cyan] Start Web Admin UI")

    choice = Prompt.ask("Enter a choice (1/2/3)", choices=["1", "2", "3"])

    if choice == "1":
        while True:
            interactive_add_account(console)
            if Prompt.ask("Continue adding accounts? (y/n)", choices=["y", "n"]) == "n":
                break
    elif choice == "2":
        from core.tasks import runTasks

        asyncio.run(runTasks())
    else:
        from webui.app import run_web_app

        run_web_app()


def build_parser():
    parser = argparse.ArgumentParser(description="QQ SparkFlow")
    parser.add_argument("--doTask", action="store_true", help="Run the message task immediately")
    parser.add_argument("--listen", action="store_true", help="Start the reply WebSocket listener")
    parser.add_argument("--web", action="store_true", help="Start the Web Admin UI")
    parser.add_argument("--host", default=None, help="Web UI bind host")
    parser.add_argument("--port", type=int, default=None, help="Web UI bind port")
    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    if args.doTask:
        from core.tasks import runTasks

        asyncio.run(runTasks())
    elif args.listen:
        from core.reply_listener import start_reply_listener

        asyncio.run(start_reply_listener())
    elif args.web:
        from webui.app import run_web_app

        run_web_app(host=args.host, port=args.port)
    else:
        interactive_cli()
