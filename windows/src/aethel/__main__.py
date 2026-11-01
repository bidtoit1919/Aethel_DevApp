import sys

from .app import AethelApplication


def main():
    sys.exit(AethelApplication().run(sys.argv))


if __name__ == "__main__":
    main()
