"""Student implementations for PyBryt"""

__all__ = ["StudentImplementation", "check"]

import os
import dill
import base64
import nbformat
import inspect

from contextlib import contextmanager
from types import FrameType
from typing import Any, Dict, List, NoReturn, Optional, Tuple, Union

from .execution import (
    create_collector, execute_notebook, _get_tracing_frame, NBFORMAT_VERSION, tracing_off, 
    tracing_on, TRACING_VARNAME
)
from .reference import generate_report, ReferenceImplementation, ReferenceResult


class StudentImplementation:
    """
    A student implementation class for handling the execution of student work and manging the 
    memory footprint generated by that execution.

    Args:
        path_or_nb (``str`` or ``nbformat.NotebookNode``): the submission notebook or the path to it
        addl_filenames (``list[str]``, optional): additional filenames to trace inside during 
            execution
        output (``str``, optional): a path at which to write executed notebook
    """

    nb: Optional[nbformat.NotebookNode]
    """the submission notebook"""

    nb_path: Optional[str]
    """the path to the notebook file"""

    values: List[Tuple[Any, int]]
    """the memory footprint (a list of tuples of objects and their timestamps)"""

    steps: int
    """number of execution steps"""

    def __init__(
        self, path_or_nb: Optional[Union[str, nbformat.NotebookNode]], addl_filenames: List[str] = [],
        output: Optional[str] = None
    ):
        if path_or_nb is None:
            self.nb = None
            self.nb_path = None
            return
        if isinstance(path_or_nb, str):
            self.nb = nbformat.read(path_or_nb, as_version=NBFORMAT_VERSION)
            self.nb_path = path_or_nb
        elif isinstance(path_or_nb, nbformat.NotebookNode):
            self.nb = path_or_nb
            self.nb_path = ""
        else:
            raise TypeError(f"path_or_nb is of unsupported type {type(path_or_nb)}")

        self._execute(addl_filenames=addl_filenames, output=output)

    def _execute(self, addl_filenames: List[str] = [], output: Optional[str] = None) -> NoReturn:
        """
        Executes the notebook ``self.nb``.

        Args:
            addl_filenames (``list[str]``, optional): additional filenames to trace inside during 
                execution
            output (``str``, optional): a path at which to write executed notebook
        """
        self.steps, self.values = execute_notebook(
            self.nb, self.nb_path, addl_filenames=addl_filenames, output=output
        )

    @classmethod
    def from_footprint(cls, footprint: List[Tuple[Any, int]], steps: int) -> 'StudentImplementation':
        """
        Create a student implementation object from a memory footprint directly, rather than by
        executing a notebook. Leaves the ``nb`` and ``nb_path`` instance variables of the resulting 
        object empty.

        Args:
            footprint (``list[tuple[object, int]]``): the memory footprint
            steps (``int``): the number of execution steps
        """
        stu = cls(None)
        stu.steps = steps
        stu.values = footprint
        return stu

    def dump(self, dest: str = "student.pkl") -> NoReturn:
        """
        Pickles this student implementation to a file.

        Args:
            dest (``str``, optional): the path to the file
        """
        with open(dest, "wb+") as f:
            dill.dump(self, f)

    def dumps(self) -> str:
        """
        Pickles this student implementation to a base-64-encoded string.

        Returns:
           ``str``: the pickled and encoded student implementation
        """
        bits = dill.dumps(self)
        return base64.b64encode(bits).decode("ascii")

    @staticmethod
    def load(file: str) -> Union['StudentImplementation']:
        """
        Unpickles a student implementation from a file.

        Args:
            file (``str``): the path to the file
        
        Returns:
            :py:class:`StudentImplementation<pybryt.StudentImplementation>`: the unpickled student 
            implementation
        """
        with open(file, "rb") as f:
            instance = dill.load(f)
        return instance

    @staticmethod
    def loads(data: str) -> "StudentImplementation":
        """
        Unpickles a student implementation from a base-64-encoded string.

        Args:
            data (``str``): the pickled and encoded student implementation
        
        Returns:
            :py:class:`StudentImplementation<pybryt.StudentImplementation>`: the unpickled student 
            implementation
        """
        return dill.loads(base64.b64decode(data.encode("ascii")))

    def check(self, ref: Union[ReferenceImplementation, List[ReferenceImplementation]], group=None) -> \
            Union[ReferenceResult, List[ReferenceResult]]:
        """
        Checks this student implementation against a single or list of reference implementations.
        Returns the :py:class:`ReferenceResult<pybryt.ReferenceResult>` object(s) resulting from 
        those checks.

        Args:
            ref (``ReferenceImplementation`` or ``list[ReferenceImplementation]``): the reference(s)
                to run against
            group (``str``, optional): if specified, only annotations in this group will be run

        Returns:
            ``ReferenceResult`` or ``list[ReferenceResult]``: the results of the reference 
            implementation checks
        """
        if isinstance(ref, ReferenceImplementation):
            return ref.run(self.values, group=group)
        elif isinstance(ref, list):
            return [r.run(self.values, group=group) for r in ref]
        else:
            raise TypeError(f"check cannot take values of type {type(ref)}")

    def check_plagiarism(self, student_impls: List["StudentImplementation"], **kwargs) -> List[ReferenceResult]:
        """
        Checks this student implementation against a list of other student implementations for 
        plagiarism. Uses :py:meth:`create_references<pybryt.plagiarism.create_references>` to create
        a randomly-generated reference implementation from this student implementation and runs it
        against each of the implementations in ``student_impls`` using 
        :py:meth:`get_impl_results<pybryt.plagiarism.get_impl_results>`.

        Args:
            student_impls (``list[StudentImplementation]``): other student implementations to run
                against
            **kwargs: keyword arguments passed to 
                :py:meth:`create_references<pybryt.plagiarism.create_references>` and 
                :py:meth:`get_impl_results<pybryt.plagiarism.get_impl_results>`
        
        Returns:
            ``list[ReferenceResult]`` or ``numpy.ndarray``: the results of each student 
            implementation in ``student_impls`` when run against this student implementation
        """
        refs = create_references([self], **kwargs)
        return get_impl_results(refs[0], student_impls, **kwargs)


class check:
    """
    A context manager for running a block of student code against a reference implementation.

    This context manager, designed to be used in students' notebooks, can be used to check a block
    of student code against one or a series of reference implementations. The context manager turns
    on tracing before launching the block and captures the memory footprint that is created while
    the block is executed. It prints out a report upon exiting with information about the passing or
    failing of each reference and the messages returned.

    As an example, the block below uses this context manager to test a student's implementation of
    a Fibonacci generator ``fiberator``:

    .. code-block:: python

        with pybryt.check("fiberator.pkl"):
            fib = fiberator()
            for _ in range(100):
                next(fib)

    Args:
        ref (``Union[str, ReferenceImplementation, list[str], list[ReferenceImplementation]]``): the
            reference(s) to check against or the path(s) to them
        report_on_error (``bool``, optional): whether to print the report when an error is thrown
            by the block
        show_only (one of ``{'satisified', 'unsatisfied', None}``, optional): which types of
            reference results to include in the report; if ``None``, all are included
        **kwargs: additional keyword arguments passed to ``pybryt.execution.create_collector``
    """

    _ref: List[ReferenceImplementation]
    """the references being checked against"""

    _report_on_error: bool
    """whether to print the report when an error is thrown by the block"""

    _show_only: Optional[str]
    """which types of eference results to include in the report"""

    _frame: Optional[FrameType]
    """the frame containing the student's code"""

    _observed: Optional[List[Tuple[Any, int]]]
    """the memory footprint"""

    _kwargs: Dict[str, Any]
    """keyword arguments passed to ``pybryt.execution.create_collector``"""

    def __init__(
        self, ref: Union[str, ReferenceImplementation, List[str], List[ReferenceImplementation]], 
        report_on_error: bool = True, show_only: Optional[str] = None, **kwargs
    ):
        if isinstance(ref, str):
            ref = ReferenceImplementation.load(ref)
        if isinstance(ref, ReferenceImplementation):
            ref = [ref]
        if isinstance(ref, list):
            if len(ref) == 0:
                raise ValueError("Cannot check against an empty list of references")
            if not all(isinstance(r, ReferenceImplementation) for r in ref):
                if not all(isinstance(r, str) for r in ref):
                    raise TypeError("Invalid values in the reference list")
                ref = [ReferenceImplementation.load(r) for r in ref]
        if not all(isinstance(r, ReferenceImplementation) for r in ref):
            raise TypeError("Invalid values provided for reference(s)")

        self._ref = ref
        self._kwargs = kwargs
        self._show_only = show_only
        self._frame = None
        self._observed = None
        self._report_on_error = report_on_error

    def __enter__(self):
        if _get_tracing_frame() is not None:
            return  # if already tracing, no action required

        else:
            self._observed, cir = create_collector(**self._kwargs)
            self._frame = inspect.currentframe().f_back
            self._frame.f_globals[TRACING_VARNAME] = True

            tracing_on(tracing_func=cir)

    def __exit__(self, exc_type, exc_value, traceback):
        tracing_off(save_func=False)

        if self._frame is not None:
            self._frame.f_globals[TRACING_VARNAME] = False

            if exc_type is None or self._report_on_error:
                stu = StudentImplementation.from_footprint(self._observed, max(t[1] for t in self._observed))
                res = stu.check(self._ref)
                report = generate_report(res, show_only=self._show_only)
                if report:
                    print(report)

        return False


from .plagiarism import create_references, get_impl_results
