"""
main.py — Entry point for the unezquake installer GUI.
"""

import sys
from GUI import UnezquakeInstallerApp


def main():
    """Main entry point."""
    try:
        app = UnezquakeInstallerApp()
        app.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nFatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

