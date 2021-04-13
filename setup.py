import pathlib, setuptools, sys

install_requires = []
if sys.platform != "cygwin":
  install_requires.append("psutil")

here = pathlib.Path(__file__).parent
with open(here/'README.md', encoding='utf-8') as f:
  long_description = f.read()

setuptools.setup(
  name = "slurm-python-utils",
  packages = setuptools.find_packages(include=["job_lock"]),
  author = "Heshy Roskes",
  author_email = "heshyr@gmail.com",
  url = "https://github.com/hroskes/slurm-python-utils",
  install_requires = install_requires,
  long_description = long_description,
  long_description_content_type = 'text/markdown',
)
