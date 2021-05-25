import contextlib, datetime, itertools, os, pathlib, re, subprocess, sys, time, uuid
if sys.platform != "cygwin":
  import psutil

def rm_missing_ok(path):
  if sys.version_info >= (3, 8):
    return path.unlink(missing_ok=True)
  else:
    try:
      return path.unlink()
    except FileNotFoundError:
      pass

def SLURM_JOBID():
  return os.environ.get("SLURM_JOBID", None)

def jobinfo():
  if SLURM_JOBID() is not None:
    return "SLURM", 0, SLURM_JOBID()
  return sys.platform, uuid.getnode(), os.getpid()

def slurm_rsync_input(filename, *, destfilename=None, copylinks=True):
  filename = pathlib.Path(filename)
  if destfilename is None: destfilename = filename.name
  destfilename = pathlib.Path(destfilename)
  if destfilename.is_absolute(): raise ValueError(f"destfilename {destfilename} has to be a relative path")
  if SLURM_JOBID() is not None:
    tmpdir = pathlib.Path(os.environ["TMPDIR"])
    destfilename = tmpdir/destfilename
    try:
      subprocess.check_call(["rsync", "-azvP"+("L" if copylinks else ""), os.fspath(filename), os.fspath(destfilename)])
    except subprocess.CalledProcessError:
      return filename
    return destfilename
  else:
    return filename

@contextlib.contextmanager
def slurm_rsync_output(filename, *, copylinks=True):
  filename = pathlib.Path(filename)
  if SLURM_JOBID() is not None:
    tmpdir = pathlib.Path(os.environ["TMPDIR"])
    tmpoutput = tmpdir/filename.name
    yield tmpoutput
    subprocess.check_call(["rsync", "-azvP"+("L" if copylinks else ""), os.fspath(tmpoutput), os.fspath(filename)])
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

class JobLock(object):
  def __init__(self, filename, outputfiles=[], checkoutputfiles=True, inputfiles=[], checkinputfiles=True, corruptfiletimeout=None):
    self.filename = pathlib.Path(filename)
    self.fd = self.f = None
    self.bool = False
    self.outputfiles = [pathlib.Path(_) for _ in outputfiles]
    self.inputfiles = [pathlib.Path(_) for _ in inputfiles]
    self.checkoutputfiles = outputfiles and checkoutputfiles
    self.checkinputfiles = inputfiles and checkinputfiles
    self.removed_failed_job = False
    self.corruptfiletimeout = corruptfiletimeout

  @property
  def wouldbevalid(self):
    if self: return True
    with self:
      return bool(self)

  def runningjobinfo(self, exceptions=False, compatibility=True):
    try:
      with open(self.filename) as f:
        contents = f.read()
        try:
          jobtype, cpuid, jobid = contents.split()
        except ValueError:
          if not compatibility: raise
          #compatibility with older version of job_lock
          jobtype = "SLURM"
          cpuid = 0
          jobid = int(contents)
        cpuid = int(cpuid)
        jobid = int(jobid)
        return jobtype, cpuid, jobid
    except (IOError, OSError, ValueError):
      if exceptions: raise
      return None, None, None

  def __open(self):
    self.fd = os.open(self.filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

  @property
  def iterative_lock_filename(self):
    match = re.match("[.]lock(?:_([0-9]+))?$", self.filename.suffix)
    if match:
      n = match.group(1)
      if n is None: n = 1
      n = int(n)
      return self.filename.with_suffix(f".lock_{n+1}")
    else:
      return self.filename.with_suffix(self.filename.suffix+".lock")

  def __enter__(self):
    removed_failed_job = False
    if self.checkoutputfiles and all(_.exists() for _ in self.outputfiles) and not self.filename.exists():
      return None
    if self.checkinputfiles and not all(_.exists() for _ in self.inputfiles):
      return None
    try:
      self.__open()
    except FileExistsError:
      #check if the job died without removing the lock
      #however this needs another job lock, because it has
      #a race condition: two jobs could be looking if the previous
      #job failed at the same time, and one of them could remove
      #the lock created by the other one
      with JobLock(self.iterative_lock_filename) as iterative_lock:
        if not iterative_lock: return None
        try:
          oldjobinfo = self.runningjobinfo(exceptions=True)
        except (IOError, OSError):
          try:
            self.__open()
          except FileExistsError:
            return None
        except ValueError:
          if self.corruptfiletimeout is not None:
            modified = datetime.datetime.fromtimestamp(self.filename.stat().st_mtime)
            now = datetime.datetime.now()
            if now - modified >= self.corruptfiletimeout:
              for outputfile in self.outputfiles:
                rm_missing_ok(outputfile)
              rm_missing_ok(self.filename)
              removed_failed_job = True
              try:
                self.__open()
              except FileExistsError:
                return None
            else:
              return None
          else:
            return None
        else:
          if jobfinished(*oldjobinfo):
            for outputfile in self.outputfiles:
              rm_missing_ok(outputfile)
            rm_missing_ok(self.filename)
            removed_failed_job = True
            try:
              self.__open()
            except FileExistsError:
              return None
          else:
            return None

    self.f = os.fdopen(self.fd, 'w')

    message = " ".join(str(_) for _ in jobinfo())
    try:
      self.f.write(message+"\n")
    except (IOError, OSError):
      pass
    try:
      self.f.close()
    except (IOError, OSError):
      pass
    self.bool = True
    self.removed_failed_job = removed_failed_job
    return self

  def __exit__(self, exc_type, exc, traceback):
    if self:
      if exc is not None:
        for outputfile in self.outputfiles:
          rm_missing_ok(outputfile)
      rm_missing_ok(self.filename)
    self.fd = self.f = None
    self.bool = self.removed_failed_job = False

  def __bool__(self):
    return self.bool

def jobfinished(jobtype, cpuid, jobid):
  if jobtype == "SLURM":
    try:
      output = subprocess.check_output(["squeue", "--job", str(jobid)], stderr=subprocess.STDOUT)
      if str(jobid).encode("ascii") in output: return False #job is still running
      return True #job is finished
    except FileNotFoundError:  #no squeue
      return None  #we don't know if the job finished
    except subprocess.CalledProcessError as e:
      if b"slurm_load_jobs error: Invalid job id specified" in e.output:
        return True #job is finished
      print(e.output)
      raise
  else:
    myjobtype, mycpuid, myjobid = jobinfo()
    if myjobtype != jobtype: return None #we don't know if the job finished
    if mycpuid != cpuid: return None #we don't know if the job finished
    if jobid == myjobid: return False #job is still running
    if sys.platform == "cygwin":
      psoutput = subprocess.check_output(["ps", "-s"])
      lines = psoutput.split(b"\n")
      ncolumns = len(lines[0])
      for line in lines[1:]:
        if not line: continue
        if int(line.split(maxsplit=1)[0]) == jobid:
          return False #job is still running
      return True #job is finished
    else:
      for process in psutil.process_iter():
        if jobid == process.pid:
          return False #job is still running
      return True #job is finished

class JobLockAndWait(JobLock):
  def __init__(self, name, delay, *, printmessage=None, task="doing this", maxiterations=1000, **kwargs):
    super().__init__(name, **kwargs)
    self.delay = delay
    if printmessage is None:
      printmessage = "Another process is already {task}.  Waiting {delay} seconds."
    printmessage = printmessage.format(delay=delay, task=task)
    self.__printmessage = printmessage
    self.niterations = 0
    self.maxiterations = maxiterations

  def __enter__(self):
    for self.niterations in itertools.count(1):
      if self.niterations > self.maxiterations:
        raise RuntimeError(f"JobLockAndWait still did not succeed after {self.maxiterations} iterations")
      result = super().__enter__()
      if result:
        return result
      print(self.__printmessage)
      time.sleep(self.delay)
