"""
This convenient shell script allows one to use Jinja2 to
template a file in place, and pass context from invocation flags.

For example, if you have the template:

$ cat hello.txt
Hello, {{ name }}!

You can use the following:
$ python template-files.py hello.txt --name=World
$ cat hello.txt
Hello, World!

You can assign multiple values by passing the same name multiple times.

For example:
$ cat hello-multiple.txt
{% for name in names %}
Hello, {{ name }}!
{% endfor %}

$ python template-files.py hello-multiple.txt --name=World --name=Atlantis
$ cat hello-multiple.txt
Hello, World!
Hello, Atlantis!
"""

from typing import Union, List, Dict

import tempfile
import sys
import os
import shutil
import jinja2


def main(path: str, *args: str) -> None:
    template = jinja2.Template(open(path, "r").read())
    context: Dict[str, Union[str, List[str]]] = {}
    i = 0
    while i < len(args):
        key_flag = args[i]
        value = args[i + 1]
        if key_flag.startswith("--"):
            key = key_flag[2:].strip()
            if key in context:
                if not isinstance(context[key], list):
                    context[key] = [context[key]]  # type: ignore
                context[key].append(value.strip())  # type: ignore
            else:
                context[key] = value.strip()
            i += 2
        else:
            i += 1
    fd, tmp = tempfile.mkstemp()
    os.close(fd)
    with open(tmp, "w") as fh:
        fh.write(template.render(**context))
    os.remove(path)
    shutil.copy(tmp, path)
    os.remove(tmp)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise ValueError(
            "USAGE: python3 template-files.py <template_file> *<arg>=<value>"
        )
    main(sys.argv[1], *sys.argv[2:])
