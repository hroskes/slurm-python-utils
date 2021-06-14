import contextlib, datetime, os, pathlib, subprocess, tempfile, time, unittest
from job_lock import clean_up_old_job_locks, JobLock, JobLockAndWait, jobinfo

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
      self.assertEqual(lock1.iterative_lock_filename, self.tmpdir/"lock1.lock_2")
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
           1234567   RUNNING
           1234568   PENDING
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
    with open(self.tmpdir/"lock5.lock", "w") as f:
      f.write("SLURM 0 1234568")
    with open(self.tmpdir/"lock6.lock", "w") as f:
      f.write("1234568")

    with JobLock(self.tmpdir/"lock1.lock") as lock1:
      self.assertFalse(lock1)
    with JobLock(self.tmpdir/"lock2.lock") as lock2:
      self.assertFalse(lock2)
    with JobLock(self.tmpdir/"lock3.lock") as lock3:
      self.assertTrue(lock3)
    with JobLock(self.tmpdir/"lock4.lock") as lock4:
      self.assertTrue(lock4)
    with JobLock(self.tmpdir/"lock5.lock") as lock5:
      self.assertTrue(lock5)
    with JobLock(self.tmpdir/"lock6.lock") as lock6:
      self.assertTrue(lock6)

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
           1234567   RUNNING
      '
      sed -i s/1234567/1234568/g $0
    """.lstrip()
    with open(self.tmpdir/"squeue", "w") as f:
      f.write(dummysqueue)
    (self.tmpdir/"squeue").chmod(0o0777)
    os.environ["PATH"] = f"{self.tmpdir}:"+os.environ["PATH"]

    with JobLockAndWait(self.tmpdir/"lock2.lock", 0.001, maxiterations=10) as lock2:
      self.assertEqual(lock2.niterations, 2)

  def testCorruptFileTimeout(self):
    with open(self.tmpdir/"lock1.lock_2", "w") as f: pass
    with open(self.tmpdir/"lock1.lock_5", "w") as f: pass
    with open(self.tmpdir/"lock1.lock_30", "w") as f: pass
    time.sleep(1)
    with open(self.tmpdir/"lock1.lock_10", "w") as f: pass
    with open(self.tmpdir/"lock1.lock", "w") as f: pass
    with JobLock(self.tmpdir/"lock1.lock", corruptfiletimeout=datetime.timedelta(seconds=1)) as lock:
      self.assertFalse(lock)
    self.assertFalse((self.tmpdir/"lock1.lock_2").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_5").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_10").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_30").exists())
    time.sleep(1)
    with JobLock(self.tmpdir/"lock1.lock") as lock:
      self.assertFalse(lock)
    with JobLock(self.tmpdir/"lock1.lock", corruptfiletimeout=datetime.timedelta(seconds=10)) as lock:
      self.assertFalse(lock)
    with JobLock(self.tmpdir/"lock1.lock", corruptfiletimeout=datetime.timedelta(seconds=1)) as lock:
      self.assertTrue(lock)
    self.assertFalse((self.tmpdir/"lock1.lock_5").exists())
    self.assertFalse((self.tmpdir/"lock1.lock_10").exists())
    self.assertFalse((self.tmpdir/"lock1.lock_30").exists())

  def testCleanUp(self):
    with open(self.tmpdir/"lock1.lock_2", "w") as f: pass
    with open(self.tmpdir/"lock1.lock_5", "w") as f: pass
    with open(self.tmpdir/"lock1.lock_30", "w") as f: pass
    time.sleep(1)
    with open(self.tmpdir/"lock1.lock_10", "w") as f: pass
    clean_up_old_job_locks(self.tmpdir, howold=datetime.timedelta(seconds=1), dryrun=True)
    self.assertTrue((self.tmpdir/"lock1.lock_2").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_5").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_10").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_30").exists())
    time.sleep(1)
    clean_up_old_job_locks(self.tmpdir, howold=datetime.timedelta(seconds=1), dryrun=True)
    self.assertTrue((self.tmpdir/"lock1.lock_2").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_5").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_10").exists())
    self.assertTrue((self.tmpdir/"lock1.lock_30").exists())
    clean_up_old_job_locks(self.tmpdir, howold=datetime.timedelta(seconds=1))
    self.assertFalse((self.tmpdir/"lock1.lock_2").exists())
    self.assertFalse((self.tmpdir/"lock1.lock_5").exists())
    self.assertFalse((self.tmpdir/"lock1.lock_10").exists())
    self.assertFalse((self.tmpdir/"lock1.lock_30").exists())
