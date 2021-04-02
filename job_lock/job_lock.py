import contextlib
import os
import pathlib
import subprocess

def SLURM_JOBID(): return os.environ.get("SLURM_JOBID", None)

def slurm_rsync_input(filename, *, destfilename=None):
    filename = pathlib.Path(filename)
    if destfilename is None: destfilename = filename.name
    destfilename = pathlib.Path(destfilename)
    if destfilename.is_absolute(): raise ValueError(f"destfilename {destfilename} has to be a relative path")
    if SLURM_JOBID() is not None:
        tmpdir = pathlib.Path(os.environ["TMPDIR"])
        destfilename = tmpdir/destfilename
        try:
            subprocess.check_call(["rsync", "-azvP", os.fspath(filename), os.fspath(destfilename)])
        except subprocess.CalledProcessError:
            return filename
        return destfilename
    else:
        return filename

@contextlib.contextmanager
def slurm_rsync_output(filename):
    filename = pathlib.Path(filename)
    if SLURM_JOBID() is not None:
        tmpdir = pathlib.Path(os.environ["TMPDIR"])
        tmpoutput = tmpdir/filename.name
        yield tmpoutput
        subprocess.check_call(["rsync", "-azvP", os.fspath(tmpoutput), os.fspath(filename)])
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
    def __init__(self, filename, message=None, outputfiles=[], inputfiles=[]):
        self.filename = pathlib.Path(filename)
        if message is None: message = SLURM_JOBID
        self.__message = message
        self.fd = self.f = None
        self.bool = False
        self.outputfiles = [pathlib.Path(_) for _ in outputfiles]
        self.inputfiles = [pathlib.Path(_) for _ in inputfiles]

    @property
    def wouldbevalid(self):
        if self: return True
        with self:
            return bool(self)

    @property
    def runningjobid(self):
        try:
            with open(self.filename) as f:
                return int(f.read())
        except (IOError, ValueError):
            return None

    def __open(self):
        self.fd = os.open(self.filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    def __enter__(self):
        if all(_.exists() for _ in self.outputfiles) and not self.filename.exists():
            return None
        if not all(_.exists() for _ in self.inputfiles):
            return None
        try:
            self.__open()
        except OSError:
            if self.__message is SLURM_JOBID:
                try:
                    with open(self.filename) as f:
                        oldjobid = int(f.read())
                except IOError:
                    try:
                        self.__open()
                    except OSError:
                        return None
                except ValueError:
                    return None
                else:
                    if jobexists(oldjobid):
                        return None
                    else:
                        for outputfile in self.outputfiles:
                            outputfile.unlink(missing_ok=True)
                        self.filename.unlink(missing_ok=True)
                        try:
                            self.__open()
                        except OSError:
                            return None
            else:
                return None

        self.f = os.fdopen(self.fd, 'w')

        if self.__message is SLURM_JOBID:
            self.__message = self.__message()
        try:
            if self.__message is not None:
                self.f.write(self.__message+"\n")
        except IOError:
            pass
        try:
            self.f.close()
        except IOError:
            pass
        self.bool = True
        return True

    def __exit__(self, exc_type, exc, traceback):
        if self:
            if exc is not None:
                for outputfile in self.outputfiles:
                    outputfile.unlink(missing_ok=True)
            self.filename.unlink(missing_ok=True)
        self.fd = self.f = None
        self.bool = False

    def __bool__(self):
        return self.bool

def jobexists(jobid):
        try:
            output = subprocess.check_output(["squeue", "--job", str(jobid)], stderr=subprocess.STDOUT)
            return str(jobid).encode("ascii") in output
        except subprocess.CalledProcessError as e:
            if b"slurm_load_jobs error: Invalid job id specified" in e.output:
                return False
            print(e.output)
            raise
