#!/usr/bin/env python
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE",
                      "tests.testapp.settings")

from django_nose import NoseTestSuiteRunner


def runtests(*test_args, **kwargs):
    if not test_args:
        test_args = ['tests']
    # Do not prompt to destroy existing db
    kwargs.setdefault('interactive', False)

    test_runner = NoseTestSuiteRunner(**kwargs)

    failures = test_runner.run_tests(test_args)
    sys.exit(failures)


if __name__ == '__main__':
    runtests()
