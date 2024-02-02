Notice
======

2022-04-27: This library is currently unmaintained, since I no longer use Django. If there is any interest, I'm still happy to review pull requests and consider adding maintainers. - @lucaswiman


django-predicate
================

django-predicate provides a Q like object to facilitate the question: "would
this model instance be part of a query" but without running the query or even
saving the object.

Quickstart
----------

Install django-predicate:

.. code-block:: console

    pip install django-predicate

Then use the ``P`` object just as you would ``Q`` objects:

.. code-block:: python

    from predicate import P

    p = P(some_field__startswith="hello", age__gt=20)

You can then call the ``eval`` method with a model instance to check whether it
passes the conditions:

.. code-block:: pycon

    model_instance = MyModel(some_field="hello there", age=21)
    other_model_instance = MyModel(some_field="hello there", age=10)
    p.eval(model_instance)
    >>> True
    p.eval(other_model_instance)
    >>> False

or you can use Python's ``in`` operator.

.. code-block:: pycon

    model_instance in p
    >>> True

Even though a predicate is not a true container class - it can be used as (and
was designed as being) a virtual "set" of objects that meets some condiiton.

Like Q objects, P objects can be ``&``'ed  and ``|``'ed together to form more
complex logic groupings.

In fact, P objects are actually a subclass of Q objects, so you can use them in
queryset filter statements:

.. code-block:: python

    qs = MyModel.objects.filter(p)


P objects also support ``QuerySet``-like filtering operations that can be
applied to an arbitrary iterable: ``P.get(iterable)``, ``P.filter(iterable)``,
and ``P.exclude(iterable)``:

.. code-block:: pycon

    model_instance = MyModel(some_field="hello there", age=21)
    other_model_instance = MyModel(some_field="hello there", age=10)
    p.filter([model_instance, other_model_instance]) == [model_instance]
    >>> True
    p.get([model_instance, other_model_instance]) == model_instance
    >>> True
    p.exclude([model_instance, other_model_instance]) == [other_model_instance]
    >>> True


If you have a situation where you want to use querysets and predicates based on
the same conditions, it is far better to start with the predicate. Because of
the way querysets assume a SQL context, it is non-trivial to reverse engineer
them back into a predicate. However as seen above, it is very straightforward
to create a queryset based on a predicate.


Development
-----------

These instructions assume you have Postgres installed and all referenced Python versions installed and activated, e.g. with Pyenv.

To run the tests locally, do the following:

1. Clone this repo.
2. Start Postgres in the background for the Postgres tests with ``postgres -D ~/postgres``.
3. Activate all tested Python versions used in this repo: ``pyenv local 3.6 3.7 3.10``.
4. (Optional) Create a virtualenv and activate it: ``python -m venv .venv``, ``source .venv/bin/activate``.
5. (Optional) Upgrade pip to prevent platform issues ``pip install --upgrade pip``
6. Install Tox for running tests: ``pip install tox``.
7. Run all tests by issuing command ``tox`` with no arguments.


Changelog
-----------

2.0.1 
^^^^^

* Added support for Python 3.7 and 3.10, and Django 2.2, 3.2, and 4.1 (see `tox.ini` for compatible Python/Django version tuples).
* Converted test runner from Nose to Pytest.
* **BREAKING** Dropped support for Python 2.7, Python 3.5, and Django 1.9.


2.0.0 (Unreleased)
^^^^^^^^^^^^^^^^^^

This version was pushed to Master but was not pushed to PyPI.

* Added deprecation warning to README.
* Added Travis CI config.
* **BREAKING**  Dropped support for Django 1.7 and 1.8.


1.4.0
^^^^^

This version and below aren't covered in this changelog.
