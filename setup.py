import setuptools

setuptools.setup(
  name = "slurm-python-utils",
  packages = setuptools.find_packages(include=["job_lock"]),
  author = "Heshy Roskes",
  author_email = "heshyr@gmail.com",
  url = "https://github.com/hroskes/slurm-python-utils",
)
