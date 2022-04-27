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

.. code-block:: python

    model_instance = MyModel(some_field="hello there", age=21)
    other_model_instance = MyModel(some_field="hello there", age=10)
    p.eval(model_instance)
    >>> True
    p.eval(other_model_instance)
    >>> False

or you can use Python's ``in`` operator.

.. code-block:: python

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

.. code-block:: python

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
