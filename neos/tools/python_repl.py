import logging
from typing import Annotated
from langchain_core.tools import tool
from langchain_experimental.utilities import PythonREPL
from langchain_sandbox import PyodideSandbox
import asyncio

from .decorators import log_io


# Initialize REPL and logger
repl = PythonREPL()
sandbox = PyodideSandbox(
    allow_net=True,  # Allow Pyodide to install python packages that might be required.
)
logger = logging.getLogger(__name__)


@tool
@log_io
def python_repl_sandbox_tool(
    code: Annotated[
        str, "The python code to execute to do further analysis or calculation."
    ],
):
    """Use this to execute python code and do data analysis or calculation. If you want to see the output of a value,
    you should print it out with `print(...)`. This is visible to the user."""
    if not isinstance(code, str):
        error_msg = f"Invalid input: code must be a string, got {type(code)}"
        logger.error(error_msg)
        return f"Error executing code:\n```python\n{code}\n```\nError: {error_msg}"

    logger.info("Executing Python code in sandbox")
    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(sandbox.execute(code))
        status = result.status
        if status != "success":
            stderr = result.stderr
            error_msg = f"Sandbox execution failed with status({status}) and error: {stderr}"
            logger.error(error_msg)
            raise RuntimeError(stderr)

        result_str = result.stdout
        logger.info("Code execution successful")
    except Exception as e:
        error_msg = repr(e)
        logger.error(error_msg)
        return f"Error executing code:\n```python\n{code}\n```\nError: {error_msg}"

    result_str = f"Successfully executed:\n```python\n{code}\n```\nStdout: {result}"
    return result_str


@tool
@log_io
def python_repl_tool(
    code: Annotated[
        str, "The python code to execute to do further analysis or calculation."
    ],
):
    """Use this to execute python code and do data analysis or calculation. If you want to see the output of a value,
    you should print it out with `print(...)`. This is visible to the user."""
    if not isinstance(code, str):
        error_msg = f"Invalid input: code must be a string, got {type(code)}"
        logger.error(error_msg)
        return f"Error executing code:\n```python\n{code}\n```\nError: {error_msg}"

    logger.info("Executing Python code")
    try:
        result = repl.run(code)
        # Check if the result is an error message by looking for typical error patterns
        if isinstance(result, str) and ("Error" in result or "Exception" in result):
            logger.error(result)
            return f"Error executing code:\n```python\n{code}\n```\nError: {result}"
        logger.info("Code execution successful")
    except BaseException as e:
        error_msg = repr(e)
        logger.error(error_msg)
        return f"Error executing code:\n```python\n{code}\n```\nError: {error_msg}"

    result_str = f"Successfully executed:\n```python\n{code}\n```\nStdout: {result}"
    return result_str
