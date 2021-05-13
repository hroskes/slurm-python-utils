import contextlib, os, pathlib, subprocess, tempfile, unittest
from job_lock import JobLock, JobLockAndWait, jobinfo

class TestJobLock(unittest.TestCase, contextlib.ExitStack):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    try:
      self.enter_context(contextlib.nullcontext())
    except AttributeError:
      contextlib.ExitStack.__init__(self)
  def setUp(self):
    self.tmpdir = pathlib.Path(self.enter_context(tempfile.TemporaryDirectory()))
    self.bkpenviron = os.environ.copy()
  def tearDown(self):
    del self.tmpdir
    self.close()
    os.environ.clear()
    os.environ.update(self.bkpenviron)

  def testJobLock(self):
    with JobLock(self.tmpdir/"lock1.lock") as lock1:
      self.assertTrue(lock1)
      with JobLock(self.tmpdir/"lock2.lock") as lock2:
        self.assertTrue(lock2)
      with JobLock(self.tmpdir/"lock1.lock") as lock3:
        self.assertFalse(lock3)

  def testRunningJobs(self):
    jobtype, cpuid, jobid = jobinfo()
    with open(self.tmpdir/"lock1.lock", "w") as f:
      f.write(f"{jobtype} {cpuid} {jobid}")
    with open(self.tmpdir/"lock2.lock", "w") as f:
      f.write(f"{'not'+jobtype} {cpuid} {jobid}")
    with open(self.tmpdir/"lock3.lock", "w") as f:
      f.write(f"{jobtype} {cpuid+1} {jobid}")

    with JobLock(self.tmpdir/"lock1.lock") as lock1:
      self.assertFalse(lock1)
    with JobLock(self.tmpdir/"lock2.lock") as lock2:
      self.assertFalse(lock2)
    with JobLock(self.tmpdir/"lock3.lock") as lock3:
      self.assertFalse(lock3)

    with subprocess.Popen(["cat"], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as popen:
      pid = popen.pid
      with open(self.tmpdir/"lock4.lock", "w") as f:
        f.write(f"{jobtype} {cpuid} {pid}")
      with JobLock(self.tmpdir/"lock4.lock") as lock4:
        self.assertFalse(lock4)

    with JobLock(self.tmpdir/"lock4.lock") as lock4:
      self.assertTrue(lock4)

  def testsqueue(self):
    dummysqueue = """
      #!/bin/bash
      echo '
             JOBID PARTITION     NAME     USER ST       TIME  NODES NODELIST(REASON)
           1234567 partition    myjob       me  R   12:34:56      1 mynode
      '
    """.lstrip()
    with open(self.tmpdir/"squeue", "w") as f:
      f.write(dummysqueue)
    (self.tmpdir/"squeue").chmod(0o0777)
    os.environ["PATH"] = f"{self.tmpdir}:"+os.environ["PATH"]

    with open(self.tmpdir/"lock1.lock", "w") as f:
      f.write("SLURM 0 1234567")
    with open(self.tmpdir/"lock2.lock", "w") as f:
      f.write("1234567")
    with open(self.tmpdir/"lock3.lock", "w") as f:
      f.write("SLURM 0 12345678")
    with open(self.tmpdir/"lock4.lock", "w") as f:
      f.write("12345678")

    with JobLock(self.tmpdir/"lock1.lock") as lock1:
      self.assertFalse(lock1)
    with JobLock(self.tmpdir/"lock2.lock") as lock2:
      self.assertFalse(lock2)
    with JobLock(self.tmpdir/"lock3.lock") as lock3:
      self.assertTrue(lock3)
    with JobLock(self.tmpdir/"lock4.lock") as lock4:
      self.assertTrue(lock4)

  def testJobLockAndWait(self):
    with JobLockAndWait(self.tmpdir/"lock1.lock", 0.001) as lock1:
      self.assertEqual(lock1.niterations, 1)

    with open(self.tmpdir/"lock2.lock", "w") as f:
      f.write("SLURM 0 1234567")
    with self.assertRaises(RuntimeError):
      with JobLockAndWait(self.tmpdir/"lock2.lock", 0.001, maxiterations=10) as lock2:
        pass

    dummysqueue = """
      #!/bin/bash
      echo '
             JOBID PARTITION     NAME     USER ST       TIME  NODES NODELIST(REASON)
           1234567 partition    myjob       me  R   12:34:56      1 mynode
      '
      sed -i s/1234567/1234568/g $0
    """.lstrip()
    with open(self.tmpdir/"squeue", "w") as f:
      f.write(dummysqueue)
    (self.tmpdir/"squeue").chmod(0o0777)
    os.environ["PATH"] = f"{self.tmpdir}:"+os.environ["PATH"]

    with JobLockAndWait(self.tmpdir/"lock2.lock", 0.001, maxiterations=10) as lock2:
      self.assertEqual(lock2.niterations, 2)

