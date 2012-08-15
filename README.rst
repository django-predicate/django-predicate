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

Like Q objects, P objects can be ``&``'ed  and ``|``'ed together to form more
complex logic groupings.

In fact, P objects are actually a subclass of Q objects, so you can use them in
queryset filter statements:

.. code-block:: python

    qs = MyModel.objects.filter(p)

If you have a situation where you want to use querysets and predicates based on
the same conditions, it is far better to start with the predicate. Because of
the way querysets assume a SQL context, it is non-trivial to reverse engineer
them back into a predicate. However as seen above, it is very straightforward
to create a queryset based on a predicate.
