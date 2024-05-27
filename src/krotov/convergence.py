r"""Routines for `check_convergence` in :func:`krotov.optimize.optimize_pulses`

A `check_convergence` function may be used to determine whether an optimization
is converged, and thus can be stopped before the maximum number of
iterations (`iter_stop`) is reached. A function suitable for
`check_convergence` must receive a :class:`.Result` object, and return a value
that evaluates as True or False in a Boolean context, indicating whether the
optimization has converged or not.

The :class:`.Result` object that the `check_convergence` function receives as
an argument will be up-to-date for the current iteration. That is, it will
already contain the current values from :func:`.optimize_pulses`'s `info_hook`
in :attr:`.Result.info_vals`, the current :attr:`~.Result.tau_vals`, etc.  The
:attr:`.Result.optimized_controls` attribute will contain the current optimized
pulses (defined on the intervals of :attr:`~.Result.tlist`).

The `check_convergence` function must not modify the :class:`.Result` object it
receives in any way. The proper place for custom modifications after each
iteration in :func:`.optimize_pulses` is through the `modify_params_after_iter`
routine (e.g., dynamically adjusting λₐ if convergence is too slow or pulse
updates are too large).

It is recommended that a `check_convergence` function returns None (which is
False in a Boolean context) if the optimization has not yet converged. If the
optimization has converged, `check_convergence` should return a message string
(which is True in a Boolean context). The returned string will be included in
the final :attr:`.Result.message`.

A typical usage for `check_convergence` is ending the optimization when the
error falls below a specified limit. Such a `check_convergence` function can be
generated by :func:`value_below`. Often, this "error" is the value of the
functional :math:`J_T`. However, it is up to the user to ensure that the
explicit value of :math:`J_T` can be calculated; :math:`J_T` in Krotov's method
is completely implicit, and enters the optimization only indirectly via the
`chi_constructor` passed to :func:`.optimize_pulses`. A specific
`chi_constructor` implies the minimization of the functional :math:`J_T` from
which `chi_constructor` was derived. A convergence check based on the
*explicit* value of :math:`J_T` can be realized by passing an `info_hook` that
returns the value of :math:`J_T`. This value is then stored in
:attr:`.Result.info_vals`, which is where :func:`value_below` looks for it.

An `info_hook` could also calculate and return an arbitrary measure of
*success*, not related to :math:`J_T` (e.g. a fidelity, or a concurrence).
Since we expect the optimization (the minimization of :math:`J_T`) to maximize
a fidelity, a convergence check might want to look at whether the calculated
value is *above* some threshold. This can be done via :func:`value_above`.

In addition to looking at the *value* of some figure of merit, one might want
stop the optimization when there is an insufficient improvement between
iterations. The :func:`delta_below` function generates a `check_convergence`
function for this purpose.  Multiple convergence conditions ("stop optimization
when :math:`J_T` reaches :math:`10^{-5}`, or if :math:`\Delta J_T < 10^{-6}`")
can be defined via :func:`Or`.

While Krotov's method is guaranteed to monotonically converge in the continuous
limit, this no longer strictly holds when time is discretized (in particular if
λₐ is too small). You can use :func:`check_monotonic_error` or
:func:`check_monotonic_fidelity` as a `check_convergence` function that stops
the optimization when monotonic convergence is lost.

The `check_convergence` routine may also be used to store the current state of
the optimization to disk, as a side effect. This is achieved by the routine
:func:`dump_result`, which can be chained with other convergence checks with
:func:`Or`. Dumping the current state of the optimization at regular intervals
protects against losing the results of a long running optimization in the event
of a crash.
"""
from operator import xor

import glom


__all__ = [
    'Or',
    'value_below',
    'value_above',
    'delta_below',
    'check_monotonic_error',
    'check_monotonic_fidelity',
    'dump_result',
]


def Or(*funcs):
    """Chain multiple `check_convergence` functions together in a logical Or.

    Each parameter must be a function suitable to pass to
    :func:`~krotov.optimize.optimize_pulses` as `check_convergence`. It
    must receive a :class:`.Result` object and should return None or a string
    message.

    Returns:
        callable: A function ``check_convergence(result)`` that returns the
        result of the first "non-passing" function in `*funcs`. A "non-passing"
        result is one that evaluates to True in a Boolean context (should be a
        string message)
    """

    def check_convergence(result):
        for func in funcs:
            msg = func(result)
            if bool(msg) is True:
                return msg
        return None

    return check_convergence


def value_below(limit, spec=('info_vals', glom.T[-1]), name=None, **kwargs):
    """Constructor for routine that checks if a value is below `limit`

    Args:
        limit (float or str): A float value (or str-representation of a float)
            against which to compare the value extracted from :class:`.Result`
        spec: A specification of the :class:`.Result` attribute from which to
            extract the value to compare against `limit`. Defaults to a
            specification extracting the last value in
            :attr:`.Result.info_vals` (returned by the `info_hook` passed to
            :func:`.optimize_pulses`). This should be some kind of error
            measure, e.g., the value of the functional $J_T$ that is being
            minimized.
        name (str or None): A name identifying the checked value, used for the
            message returned by the `check_convergence` routine. Defaults to
            ``str(spec)``.
        **kwargs: Keyword arguments to pass to :func:`~glom.glom` (see Note)

    Returns:
        callable: A function ``check_convergence(result)`` that extracts the
        value specified by `spec` from the :class:`.Result` object, and checks
        it against `limit`. If the value is below the `limit`, it returns an
        appropriate message string. Otherwise, it returns None.

    Note:
        The `spec` can be a callable that receives :class:`.Result` and returns
        the value to check against the limit. You should also pass a `name`
        like 'J_T', or 'error' as a label for the value.
        For more advanced use cases, `spec` can be a
        :func:`~glom.glom`-specification that extracts the value to check from
        the :class:`.Result` object as ``glom.glom(result, spec, **kwargs)``.

    Example:

        >>> check_convergence = value_below(
        ...     limit='1e-4',
        ...     spec=lambda r: r.info_vals[-1],  # same as the default spec
        ...     name='J_T'
        ... )
        >>> r = krotov.result.Result()
        >>> r.info_vals.append(1e-4)
        >>> check_convergence(r)  # returns None
        >>> r.info_vals.append(9e-5)
        >>> check_convergence(r)
        'J_T < 1e-4'
    """
    # `limit` can be a string so that it shows up as e.g. `1e-4` in the
    # resulting message, instead of some arbitrary formatting like `0.0001`

    if name is None:
        name = str(spec)

    def check_convergence(result):
        v = glom.glom(result, spec, **kwargs)
        if v < float(limit):
            return "%s < %s" % (name, limit)
        else:
            return None

    return check_convergence


def value_above(limit, spec=('info_vals', glom.T[-1]), name=None, **kwargs):
    """Constructor for routine that checks if a value is above `limit`

    Like :func:`value_below`, but for checking whether an extracted value is
    *above*, not below a value. By default, it looks at the last value in
    :attr:`.Result.info_vals`, under the assumption that the `info_hook` passed
    to :func:`.optimize_pulses` returns some figure of merit we expect to be
    maximized, like a fidelity. Note that an `info_hook` is free to return an
    arbitrary value, not necessarily the value of the functional $J_T$ that the
    optimization is minimizing (specified implicitly via the `chi_constructor`
    argument to :func:`.optimize_pulses`).

    Example:

        >>> check_convergence = value_above(
        ...     limit='0.999',
        ...     spec=lambda r: r.info_vals[-1],
        ...     name='Fidelity'
        ... )
        >>> r = krotov.result.Result()
        >>> r.info_vals.append(0.9)
        >>> check_convergence(r)  # returns None
        >>> r.info_vals.append(1 - 1e-6)
        >>> check_convergence(r)
        'Fidelity > 0.999'
    """

    if name is None:
        name = str(spec)

    def check_convergence(result):
        v = glom.glom(result, spec, **kwargs)
        if v > float(limit):
            return "%s > %s" % (name, limit)
        else:
            return None

    return check_convergence


def delta_below(
    limit,
    spec1=('info_vals', glom.T[-1]),
    spec0=('info_vals', glom.T[-2]),
    absolute_value=True,
    name=None,
    **kwargs,
):
    r"""Constructor for a routine that checks if
    $\Abs{v_1 - v_0} < \varepsilon$

    Args:
        limit (float or str): A float value (or str-representation of a float)
            for $\varepsilon$
        spec1: A :func:`~glom.glom` specification of the :class:`.Result`
            attribute from which to extract $v_1$. Defaults to a spec
            extracting the last value in :attr:`.Result.info_vals`.
        spec0: A :func:`~glom.glom` specification of the :class:`.Result`
            attribute from which to extract $v_0$.  Defaults to a spec
            extracting the last-but-one value in :attr:`.Result.info_vals`.
        absolute_value (bool): If False, check for $v_1 - v_0 < \varepsilon$,
            instead of the absolute value.
        name (str or None): A name identifying the delta, used for the
            message returned by the `check_convergence` routine. Defaults to
            ``"Δ({spec1},{spec0}"``.
        **kwargs: Keyword arguments to pass to :func:`~glom.glom`

    Note:
        You can use :func:`delta_below` to implement a check for strict
        monotonic convergence, e.g. when `info_hook` returns the optimization
        error, by flipping `spec0` and `spec1`, setting `limit` to zero, and
        setting `absolute_value` to False. See :func:`check_monotonic_error`.

    Example:

        >>> check_convergence = delta_below(limit='1e-4', name='ΔJ_T')
        >>> r = krotov.result.Result()
        >>> r.info_vals.append(9e-1)
        >>> check_convergence(r)  # None
        >>> r.info_vals.append(1e-1)
        >>> check_convergence(r)  # None
        >>> r.info_vals.append(4e-4)
        >>> check_convergence(r)  # None
        >>> r.info_vals.append(2e-4)
        >>> check_convergence(r)  # None
        >>> r.info_vals.append(1e-6)
        >>> check_convergence(r)  # None
        >>> r.info_vals.append(1e-7)
        >>> check_convergence(r)
        'ΔJ_T < 1e-4'
    """
    if name is None:
        name = "Δ(%s,%s)" % (spec1, spec0)

    def check_convergence(result):
        delayed_exc = None
        try:
            v1 = glom.glom(result, spec1, **kwargs)
        except (AttributeError, KeyError, IndexError, glom.GlomError) as exc:
            v1 = None
            delayed_exc = exc
        try:
            v0 = glom.glom(result, spec0, **kwargs)
        except (AttributeError, KeyError, IndexError, glom.GlomError) as exc:
            v0 = None
            delayed_exc = exc
        if xor((v1 is None), (v0 is None)):
            # After the first iteration, there may not be enough data to get
            # *both* v1 and v0. In this case, we just pass the check...
            return None
        else:
            # ... However, if we can access neither v1 nor v0, then something
            # is definitely wrong, and we should re-raise the original
            # exception
            if delayed_exc is not None:
                raise delayed_exc
        delta = v1 - v0
        if absolute_value:
            delta = abs(delta)
        if delta < float(limit):
            return "%s < %s" % (name, limit)
        else:
            return None

    return check_convergence


_monotonic_convergence = delta_below(
    limit=0,
    spec1=('info_vals', glom.T[-2]),
    spec0=('info_vals', glom.T[-1]),
    absolute_value=False,
    name="Loss of monotonic convergence; error decrease",
)


_monotonic_fidelity = delta_below(
    limit=0,
    spec1=('info_vals', glom.T[-1]),
    spec0=('info_vals', glom.T[-2]),
    absolute_value=False,
    name="Loss of monotonic convergence; fidelity increase",
)


def check_monotonic_error(result):
    """Check for monotonic convergence with respect to the error

    Check that the last value in :attr:`.Result.info_vals` is
    smaller than the last-but-one value. If yes, return None. If no, return an
    appropriate error message.

    This assumes that the `info_hook` passed to :func:`.optimize_pulses`
    returns the value of the functional $J_T$ (or another quantity that we
    expect to be minimized), which is then available in
    :attr:`.Result.info_vals`.

    Example:

        >>> r = krotov.result.Result()
        >>> r.info_vals.append(9e-1)
        >>> check_monotonic_error(r)  # None
        >>> r.info_vals.append(1e-1)
        >>> check_monotonic_error(r)  # None
        >>> r.info_vals.append(2e-1)
        >>> check_monotonic_error(r)
        'Loss of monotonic convergence; error decrease < 0'

    See also:
        Use :func:`check_monotonic_fidelity` for when `info_hook` returns a
        "fidelity", that is, a measure that should *increase* in each
        iteration.
    """
    # This is a wrapper for `_monotonic_convergence` just so that we can have
    # `check_monotonic_convergence` with a nice docstring.
    return _monotonic_convergence(result)


def check_monotonic_fidelity(result):
    """Check for monotonic convergence with respect to the fidelity

    This is like :func:`check_monotonic_error`, but looking for a monotonic
    *increase* in the values in :attr:`.Result.info_vals`. Thus, it is assumed
    that the `info_hook` returns a fidelity (to be maximized), not an error
    (like $J_T$, to be minimized).

    Example:
        >>> r = krotov.result.Result()
        >>> r.info_vals.append(0.0)
        >>> check_monotonic_fidelity(r)  # None
        >>> r.info_vals.append(0.2)
        >>> check_monotonic_fidelity(r)  # None
        >>> r.info_vals.append(0.15)
        >>> check_monotonic_fidelity(r)
        'Loss of monotonic convergence; fidelity increase < 0'
    """
    return _monotonic_fidelity(result)


def dump_result(filename, every=10):
    """Return a function for dumping the result every so many iterations

    For long-running optimizations, it can be useful to dump the current state
    of the optimization every once in a while, so that the result is not lost
    in the event of a crash or unexpected shutdown. This function returns a
    routine that can be passed as a `check_convergence` routine that does
    nothing except to dump the current :class:`.Result` object to a file (cf.
    :meth:`.Result.dump`). Failure to write the dump file stops the
    optimization.

    Args:
        filename (str): Name of file to dump to. This may include a field
            ``{iter}`` which will be formatted with the most recent iteration
            number, via :meth:`str.format`. Existing files will be overwritten.
        every (int): dump the :class:`.Result` every so many iterations.

    Note:
        Choose `every` so that dumping does not happen more than once every few
        minutes, at most. Dumping after every single iteration may slow down
        the optimization due to I/O overhead.

    Examples:

        * dump every 10 iterations to the same file `oct_result.dump`::

            >>> check_convergence = dump_result('oct_result.dump')

        * dump every 100 iterations to  files ``oct_result_000100.dump``,
          ``oct_result_000200.dump``, etc.::

            >>> check_convergence = dump_result(
            ...     'oct_result_{iter:06d}.dump', every=100)
    """

    every = int(every)
    if every <= 0:
        raise ValueError("every must be > 0")

    def _dump_result(result):
        iteration = result.iters[-1]
        if iteration % every == 0:
            outfile = filename.format(iter=iteration)
            try:
                result.dump(outfile)
            except IOError as exc_info:
                return "Could not store %s: %s" % (outfile, exc_info)
        return None

    return _dump_result
