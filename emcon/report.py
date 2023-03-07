import tomli
from enum import Enum
from collections import Counter
import datetime
import jinja2
import smtplib
from email.message import EmailMessage
from html2text import html2text
from dali.address import GearShort
from dali.gear.general import (
    QueryControlGearPresent,
    DTR0,
    QueryContentDTR1,
)
from dali.sequences import QueryDeviceTypes
from dali.gear.emergency import (
    QueryBatteryCharge,
    QueryTestTiming,
    QueryDurationTestResult,
    QueryRatedDuration,
    QueryEmergencyMode,
    QueryEmergencyFeatures,
    QueryEmergencyFailureStatus,
    QueryEmergencyStatus,
)
from .daliserver import DaliServer


sites = {}


class EmergencyMode(Enum):
    NORMAL = "Normal"
    INHIBIT = "Inhibit"
    REST = "Rest"
    EMERGENCY = "Emergency"
    EXTENDED_EMERGENCY = "Extended emergency"
    FUNCTION_TEST = "Function test"
    DURATION_TEST = "Duration test"
    INVALID = "Invalid"


# Value of bits 5:0 of QueryEmergencyModeResponse to EmergencyMode member
emergency_mode_values = {
    0x01: EmergencyMode.REST,
    0x02: EmergencyMode.NORMAL,
    0x04: EmergencyMode.EMERGENCY,
    0x08: EmergencyMode.EXTENDED_EMERGENCY,
    0x10: EmergencyMode.FUNCTION_TEST,
    0x20: EmergencyMode.DURATION_TEST,
}


class TestStatus(Enum):
    NOT_TESTED = "not done"
    PASS = "pass"
    FAIL = "fail"
    IN_PROGRESS = "in progress"


passing_test_status = {TestStatus.PASS, TestStatus.IN_PROGRESS}


class NextTestStatus(Enum):
    NOT_SCHEDULED = "not scheduled"
    SCHEDULED = "scheduled"
    PENDING = "pending"
    OVERDUE = "overdue"


passing_next_test_status = {NextTestStatus.SCHEDULED, NextTestStatus.PENDING}


class Bus:
    def __init__(self, d, key, site):
        self.key = key
        self.site = site
        self.hostname = d["hostname"]
        self.port = d["port"]
        self.name = d.get("name", key)
        self._ds = DaliServer(host=self.hostname, port=self.port,
                              multiple_frames_per_connection=True)

    def __enter__(self):
        return self._ds.__enter__()

    def __exit__(self, *vpass):
        self._ds.__exit__(*vpass)

    def __str__(self):
        return f"{self.site.key}/{self.key}"


class Gear:
    def __init__(self, site, d):
        self.site = site
        self.busname = d["bus"]
        self.bus = site.buses[d["bus"]]
        self.address = d["address"]
        self.name = d["name"]
        self.expected_rated_duration = d.get(
            "rated-duration", site.expected_rated_duration)
        self.expected_ft_interval = d.get(
            "function-test-interval", site.expected_ft_interval)
        self.expected_dt_interval = d.get(
            "duration-test_interval", site.expected_dt_interval)
        self.expected_timeout = d.get(
            "test-execution-timeout", site.expected_timeout)
        self.clear()

    def clear(self):
        self._summary = None
        self.timestamp = None  # Time gear information was read
        self.present = False
        self.mode = EmergencyMode.INVALID
        self.is_emergency = False
        self.rated_duration = None
        self.circuit_failure = None
        self.battery_duration_failure = None
        self.battery_failure = None
        self.emergency_lamp_failure = None
        self.battery_charge = None  # Battery percentage; float 0..100
        self.ft_state = TestStatus.NOT_TESTED
        self.dt_state = TestStatus.NOT_TESTED
        self.dt_result = None
        self.next_ft_state = NextTestStatus.NOT_SCHEDULED
        self.next_dt_state = NextTestStatus.NOT_SCHEDULED
        self.ft_interval = None  # Test interval in days
        self.dt_interval = None  # Test interval in weeks
        self.timeout = None  # Test execution timeout in days
        self.ft_delay = None  # Time to next function test in minutes
        self.dt_delay = None  # Time to next duration test in minutes

    @property
    def ft_scheduled_time(self):
        return self.timestamp + datetime.timedelta(minutes=self.ft_delay)

    @property
    def dt_scheduled_time(self):
        return self.timestamp + datetime.timedelta(minutes=self.dt_delay)

    @property
    def summary(self):
        if not self._summary:
            self._summary = self._update_summary()
        return self._summary

    def _update_summary(self):
        if not self.present:
            return "Not present"
        if not self.is_emergency:
            return "Not an emergency unit"
        if self.rated_duration != self.expected_rated_duration:
            return f"Incorrect rated duration {self.rated_duration} minutes"
        if self.ft_interval != self.expected_ft_interval:
            return "Function test interval is incorrect"
        if self.dt_interval != self.expected_dt_interval:
            return "Duration test interval is incorrect"
        if self.timeout != self.expected_timeout:
            return "Test execution timeout is incorrect"
        if self.circuit_failure:
            return "Circuit failure"
        if self.battery_duration_failure:
            return "Battery duration failure"
        if self.battery_failure:
            return "Battery failure"
        if self.emergency_lamp_failure:
            return "Emergency lamp failure"
        if self.next_ft_state not in passing_next_test_status:
            return f"Next function test {self.next_ft_state.value}"
        if self.next_dt_state not in passing_next_test_status:
            return f"Next duration test {self.next_dt_state.value}"
        if self.ft_state not in passing_test_status \
           and self.next_ft_state != NextTestStatus.PENDING:
            return f"Function test {self.ft_state.value}"
        if self.dt_state not in passing_test_status \
           and self.next_dt_state != NextTestStatus.PENDING:
            return f"Duration test {self.dt_state.value}"
        return "Pass"

    @property
    def pass_(self):
        return self.summary == "Pass"

    def dump_state(self, indent=0):
        for line in self.list_state():
            print(f"{' ' * indent}{line}")

    def list_state(self):
        r = []

        def p(s):
            r.append(s)

        p(f"Name: {self.name}")
        if not self.present:
            p("Not present")
            return r
        if not self.is_emergency:
            p("Not an emergency unit")
            return r
        if self.mode != EmergencyMode.NORMAL:
            p(f"Current mode: {self.mode.value}")
        if self.rated_duration != self.expected_rated_duration:
            p(f"Unexpected rated duration: {self.rated_duration} minutes")
        if self.ft_interval != self.expected_ft_interval:
            p(f"Unexpected function test interval: {self.ft_interval} days")
        if self.dt_interval != self.expected_dt_interval:
            p(f"Unexpected duration test interval: {self.dt_interval} weeks")
        if self.timeout != self.expected_timeout:
            p(f"Unexpected test execution timeout: {self.timeout} days")
        if self.circuit_failure:
            p("Circuit failure")
        if self.battery_duration_failure:
            p("Battery duration failure")
        if self.battery_failure:
            p("Battery failure")
        if self.emergency_lamp_failure:
            p("Emergency lamp failure")
        if self.battery_charge is not None and self.battery_charge != 100.0:
            p(f"Battery charge: {self.battery_charge:0.1f}%")
        if self.ft_state != TestStatus.PASS:
            p(f"Function test: {self.ft_state.value}")
        if self.dt_state != TestStatus.PASS:
            p(f"Duration test: {self.dt_state.value}")
            if self.dt_state == TestStatus.FAIL:
                p(f"Duration test result: {self.dt_result} minutes")
        tf = {'sep': ' ', 'timespec': 'minutes'}
        if self.next_ft_state == NextTestStatus.SCHEDULED:
            p(f"Next function test: "
              f"{self.ft_scheduled_time.isoformat(**tf)} ± 15 min")
        else:
            p(f"Next function test: {self.next_ft_state.value}")
        if self.next_dt_state == NextTestStatus.SCHEDULED:
            p(f"Next duration test: "
              f"{self.dt_scheduled_time.isoformat(**tf)} ± 15 min")
        else:
            p(f"Next duration test: {self.next_dt_state.value}")
        return r

    def update(self):
        self.clear()
        self.timestamp = datetime.datetime.now()
        with self.bus as b:
            b.send(self._read())

    def _read(self):
        a = GearShort(self.address)

        r = yield QueryControlGearPresent(a)
        if not r.value:
            return
        self.present = True

        devicetypes = yield from QueryDeviceTypes(a)
        if 1 not in devicetypes:
            return
        self.is_emergency = True

        self.rated_duration = (yield QueryRatedDuration(a)).value * 2
        features = yield QueryEmergencyFeatures(a)
        mode = yield QueryEmergencyMode(a)
        es = yield QueryEmergencyStatus(a)
        fs = yield QueryEmergencyFailureStatus(a)

        self.circuit_failure = fs.circuit_failure
        self.battery_duration_failure = fs.battery_duration_failure
        self.battery_failure = fs.battery_failure
        self.emergency_lamp_failure = fs.emergency_lamp_failure

        self.mode = emergency_mode_values.get(
            mode.raw_value[5:0], EmergencyMode.INVALID)

        if self.mode == EmergencyMode.NORMAL and es.inhibit_mode:
            self.mode = EmergencyMode.INHIBIT

        if mode.function_test:
            self.ft_state = TestStatus.IN_PROGRESS
        if mode.duration_test:
            self.dt_state = TestStatus.IN_PROGRESS

        bat = yield QueryBatteryCharge(a)
        if bat.value != "MASK":
            self.battery_charge = bat.value * 100 / 254

        if es.function_test_done_and_result_valid:
            self.ft_state = TestStatus.FAIL if fs.function_test_failed \
                else TestStatus.PASS
        if es.duration_test_done_and_result_valid:
            self.dt_result = (yield QueryDurationTestResult(a)).value * 2
            self.dt_state = TestStatus.FAIL if fs.duration_test_failed \
                else TestStatus.PASS

        if features.auto_test_capability:
            self.next_ft_state = NextTestStatus.SCHEDULED
            self.next_dt_state = NextTestStatus.SCHEDULED
            if es.function_test_pending:
                self.next_ft_state = NextTestStatus.OVERDUE \
                    if fs.function_test_max_delay_exceeded \
                       else NextTestStatus.PENDING
            if es.duration_test_pending:
                self.next_dt_state = NextTestStatus.OVERDUE \
                    if fs.duration_test_max_delay_exceeded \
                       else NextTestStatus.PENDING

            yield DTR0(4)  # function test interval
            self.ft_interval = (yield QueryTestTiming(a)).raw_value.as_integer
            yield DTR0(5)  # duration test interval
            self.dt_interval = (yield QueryTestTiming(a)).raw_value.as_integer
            yield DTR0(6)  # test execution timeout
            self.timeout = (yield QueryTestTiming(a)).raw_value.as_integer
            yield DTR0(0)  # next function test time high byte
            x = (yield QueryTestTiming(a)).raw_value.as_integer
            y = (yield QueryContentDTR1(a)).raw_value.as_integer
            self.ft_delay = ((x << 8) + y) * 15
            yield DTR0(2)  # next duration test time high byte
            x = (yield QueryTestTiming(a)).raw_value.as_integer
            y = (yield QueryContentDTR1(a)).raw_value.as_integer
            self.dt_delay = ((x << 8) + y) * 15


class Site:
    def __init__(self, d, key):
        self.key = key
        self.name = d["name"]
        self.email_to = d["email-to"]
        self.email_from = d["email-from"]
        self.buses = {k: Bus(v, key=k, site=self)
                      for k, v in d["buses"].items()}
        self.expected_rated_duration = d.get("rated-duration", 180)
        self.expected_ft_interval = d.get("function-test-interval", 7)
        self.expected_dt_interval = d.get("duration-test_interval", 52)
        self.expected_timeout = d.get("test-execution-timeout", 7)
        self.gear = [Gear(self, g) for g in d["gear"]]
        self.gearindex = {(g.bus, g.address): g for g in self.gear}
        self.pass_ = False
        self.results = Counter()

    def update(self, progress=None):
        self.report_time = datetime.datetime.now()
        self.pass_ = True
        self.results = Counter()
        for gear in self.gear:
            gear.update()
            self.results[gear.summary] += 1
            if not gear.pass_:
                self.pass_ = False
            if progress is not None:
                progress(gear)

    def report(self, sitename, template=None):
        env = jinja2.Environment(
            loader=jinja2.PackageLoader("emcon"),
            autoescape=jinja2.select_autoescape())
        template = env.get_template(template or "report.html")
        return template.render(sitename=sitename, site=self)

    def email_report(self, sitename, to=None):
        if to is None:
            to = ', '.join(self.email_to)
        report = self.report(sitename)
        report_plain = html2text(report)
        msg = EmailMessage()
        msg['Subject'] = f"{self.name} emergency lighting status — "\
            f"{'Pass' if self.pass_ else 'Fail'}"
        msg['From'] = self.email_from
        msg['To'] = to
        msg.preamble = "You should use a MIME-aware mail reader to view "\
            "this report.\n"
        msg.set_content(report_plain)
        msg.add_alternative(report, subtype="html")

        with smtplib.SMTP() as smtp:
            smtp.connect()
            smtp.send_message(msg)


def read_config(f):
    d = tomli.load(f)
    for k, v in d.items():
        sites[k] = Site(v, key=k)
