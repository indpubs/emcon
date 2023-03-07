import argparse
import pathlib
import sys
from . import report
from dali.address import GearShort, GearBroadcast
from dali.gear.emergency import (
    Inhibit,
    Rest,
    ReLightResetInhibit,
    StartFunctionTest,
    StartDurationTest,
    StopTest,
    StartIdentification,
    ResetFunctionTestDoneFlag,
    ResetDurationTestDoneFlag,
    ResetLampTime,
)


class CommandTracker(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, '_commands'):
            cls._commands = []
        else:
            if hasattr(cls, "command"):
                cls._commands.append(cls)


class Command(metaclass=CommandTracker):
    @classmethod
    def add_subparsers(cls, parser):
        subparsers = parser.add_subparsers(title="commands")
        for c in cls._commands:
            description = c.description if hasattr(c, "description") \
                else c.__doc__
            help = c.help if hasattr(c, "help") else description
            parser = subparsers.add_parser(
                c.command, help=help, description=description)
            parser.set_defaults(command=c)
            c.add_arguments(parser)

    @staticmethod
    def add_arguments(parser):
        pass

    @staticmethod
    def run(args):
        pass


class ListGear(Command):
    """List all configured emergency gear"""
    command = "list"

    @staticmethod
    def run(args):
        for sitename, site in report.sites.items():
            for gear in site.gear:
                print(f"{sitename}/{gear.busname}/{gear.address}: {gear.name}")


class Check(Command):
    """Check all configured emergency gear and output a status summary"""
    command = "check"

    @staticmethod
    def run(args):
        for sitename, site in report.sites.items():
            print(f"Site: {site.name}")
            if args.verbose:
                print(f"  - Rated duration: {site.expected_rated_duration} "
                      f"minutes")
                print(f"  - Function test every {site.expected_ft_interval} "
                      f"days")
                print(f"  - Duration test every {site.expected_dt_interval} "
                      f"weeks")
                print(f"  - Test required to complete within "
                      f"{site.expected_timeout} days of scheduled time")
                print("  - Gear:")

                def progress(gear):
                    print(f"    - {sitename}/{gear.busname}/{gear.address} — "
                          f"{gear.summary}")
                    gear.dump_state(indent=8)

            site.update(progress=progress if args.verbose else None)

            print(f"  - Overall state: {'Pass' if site.pass_ else 'Fail'}")
            print(f"  - Results: {site.results}")


class Email(Command):
    """Email status reports for all configured sites"""
    command = "email"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "destination", nargs="?",
            help="Email address to receive the reports, overriding those "
            "specified in the configuration file")

    @staticmethod
    def run(args):
        for sitename, site in report.sites.items():
            if args.verbose:
                print(f"Site: {site.name}")

            def progress(gear):
                if args.verbose:
                    print(f"  - {sitename}/{gear.busname}/{gear.address} — "
                          f"{gear.summary}")

            site.update(progress=progress)
            if args.destination:
                site.email_report(sitename, to=args.destination)
            else:
                site.email_report(sitename)


class _BusCommand(Command):
    """Send a single command"""
    @staticmethod
    def target(arg):
        xs = arg.split("/")
        if len(xs) < 1:
            raise ValueError("A site name must be specified")
        if len(xs) > 3:
            raise ValueError("Too many components in target")
        return xs

    @classmethod
    def add_arguments(cls, parser):
        assert hasattr(cls, "dali_command")
        parser.add_argument(
            "target", type=_BusCommand.target,
            help="Target of this command: sitename[/busname[/address]]")

    @classmethod
    def run(cls, args):
        ts = args.target
        site = report.sites.get(ts[0])
        if not site:
            print(f"emcon: error: site {ts[0]} not known")
            return 1
        if len(ts) > 1:
            bus = site.buses.get(ts[1], None)
            if not bus:
                print(f"emcon: error: bus {ts[1]} not known at site {ts[0]}")
                return 1
            buses = [bus]
        else:
            buses = list(site.buses.values())
        if len(ts) > 2:
            address = GearShort(int(ts[2]))
        else:
            address = GearBroadcast()
        for bus in buses:
            with bus as b:
                dc = cls.dali_command(address)
                if args.verbose:
                    print(f"Sending {dc} on bus {bus}")
                b.send(dc)


class IdentifyCmd(_BusCommand):
    """Start or restart a ten-second identification procedure"""
    command = "identify"
    dali_command = StartIdentification


class InhibitCmd(_BusCommand):
    """Start or restart the 15 minute Inhibit timer"""
    command = "inhibit"
    dali_command = Inhibit


class RestCmd(_BusCommand):
    """Enter Rest mode if currently in emergency mode"""
    command = "rest"
    dali_command = Rest


class ResetCmd(_BusCommand):
    """Cancel the Inhibit timer, re-light if possible if power not present"""
    command = "reset"
    dali_command = ReLightResetInhibit


class StartFunctionTestCmd(_BusCommand):
    """Request a function test"""
    command = "start-function-test"
    dali_command = StartFunctionTest


class StartDurationTestCmd(_BusCommand):
    """Request a duration test"""
    command = "start-duration-test"
    dali_command = StartDurationTest


class StopTestCmd(_BusCommand):
    """Cancel pending tests and stop any test currently in progress"""
    command = "stop-test"
    dali_command = StopTest


class ResetFunctionTestDoneCmd(_BusCommand):
    """Reset the "function test done and result valid" flag"""
    command = "reset-function-test-done"
    dali_command = ResetFunctionTestDoneFlag


class ResetDurationTestDoneCmd(_BusCommand):
    """Reset the "duration test done and result valid" flag"""
    command = "reset-duration-test-done"
    dali_command = ResetDurationTestDoneFlag


class ResetLampTimeCmd(_BusCommand):
    """Reset the lamp emergency time and lamp total operation time counters"""
    command = "reset-lamp-time"
    dali_command = ResetLampTime


def main():
    parser = argparse.ArgumentParser(
        description="Emergency lighting control")
    parser.add_argument(
        '--configfile', '-c', type=pathlib.Path,
        default=pathlib.Path("config.toml"),
        help="Path to configuration file")
    parser.add_argument(
        '--site', '-s', type=str, action="append",
        help="Only work on this site")
    parser.add_argument(
        '--verbose', '-v', action="store_true", default=False,
        help="Display progress while working")
    Command.add_subparsers(parser)

    args = parser.parse_args()

    try:
        with open(args.configfile, "rb") as f:
            report.read_config(f)
    except FileNotFoundError:
        print(f"Could not open config file '{args.configfile}'")
        sys.exit(1)

    if args.site:
        try:
            report.sites = {s: report.sites[s] for s in args.site}
        except KeyError as e:
            print(f"Unrecognised site '{e.args[0]}'")
            sys.exit(1)

    sys.exit(args.command.run(args))
