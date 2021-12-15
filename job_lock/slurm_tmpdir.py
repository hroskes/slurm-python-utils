from .job_lock import JobLockAndWait, SLURM_JOBID
import contextlib, os, pathlib, shutil, subprocess

def slurm_rsync_input(filename, *, destfilename=None, copylinks=True, silentjoblock=None, silentrsync=False):
  filename = pathlib.Path(filename)
  if destfilename is None: destfilename = filename.name
  destfilename = pathlib.Path(destfilename)
  if destfilename.is_absolute(): raise ValueError(f"destfilename {destfilename} has to be a relative path")
  if SLURM_JOBID() is not None:
    tmpdir = pathlib.Path(os.environ["TMPDIR"])
    destfilename = tmpdir/destfilename
    lockfilename = destfilename.with_suffix(".lock")
    if lockfilename == destfilename:
      lockfilename = destfilename.with_suffix(".lock_2")
    assert lockfilename != destfilename
    try:
      with JobLockAndWait(lockfilename, 10, task=f"rsyncing {filename}", silent=silentjoblock):
        args = ["-az", "--partial"]
        if copylinks: args.append("-L")
        if not silentrsync: args.append("-v", "--progress")
        print(args)
        subprocess.check_call(["rsync", *args, os.fspath(filename), os.fspath(destfilename)])
    except subprocess.CalledProcessError:
      return filename
    return destfilename
  else:
    return filename

@contextlib.contextmanager
def slurm_rsync_output(filename, *, copylinks=True, silentrsync=False):
  filename = pathlib.Path(filename)
  if SLURM_JOBID() is not None:
    tmpdir = pathlib.Path(os.environ["TMPDIR"])
    tmpoutput = tmpdir/filename.name
    yield tmpoutput
    args = ["-az", "--partial"]
    if copylinks: args.append("-L")
    if not silentrsync: args.append("-v", "--progress")
    subprocess.check_call(["rsync", *args, os.fspath(tmpoutput), os.fspath(filename)])
  else:
    yield filename

def slurm_clean_up_temp_dir():
  if SLURM_JOBID() is None: return
  tmpdir = pathlib.Path(os.environ["TMPDIR"])
  for filename in tmpdir.iterdir():
    if filename.is_dir() and not filename.is_symlink():
      shutil.rmtree(filename)
    else:
      filename.unlink()

