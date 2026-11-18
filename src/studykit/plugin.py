"""pytest plugin, loaded wherever the kit is installed: one header line saying which kit
version the tests run against and whether a newer one is out (checked at most once a day,
never failing a run)."""


def pytest_report_header(config):
    try:
        from studykit.__main__ import status_line
        return status_line()
    except Exception:
        return None
