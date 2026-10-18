"""Native cache implementation cross-checked against Python reference and real files."""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "frontend/cache-analysis"))
from cache_record import decode_metadata, rebuild_record, validate_record, salted_sha1


def fixture(body,identifier,salt,wide=False):
    chunks=[];typed=hashlib.sha1()
    def field(raw,tag):
        chunks.append(raw);typed.update(struct.pack("<I",tag));typed.update(raw)
    def string(value,wide=False):
        if value is None:field(struct.pack("<I",0xffffffff),11);return
        raw=value.encode("utf-16-le" if wide else "latin1")
        field(struct.pack("<I",len(value)),11);field(bytes([not wide]),3);field(raw,101)
    header=b"console-specific opaque response headers\0"
    field(struct.pack("<I",16),11);string("");string("Resource");string(identifier,wide);string(None)
    field(bytes(range(20)),101);field(bytes(range(20)),101);field(struct.pack("<d",123.5),29)
    field(salted_sha1(header,salt),101);field(struct.pack("<Q",len(header)),13)
    field(salted_sha1(body,salt),101);field(struct.pack("<Q",len(body)),13);field(b"\1",3)
    return b"".join(chunks)+typed.digest()+header+body


class WatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="spotless-watcher-")
        cls.root=Path(cls.temp.name);cls.home=cls.root/"state";cls.home.mkdir();cls.cache=cls.root/"cache"
        cls.resource=cls.cache/"Records"/("A"*40)/"Resource";cls.resource.mkdir(parents=True)
        cls.binary=cls.root/"core"
        command=[os.environ.get("SPOTLESS_TEST_CC","cc"),"-D_DEFAULT_SOURCE","-std=c11","-O2","-Wall","-Wextra","-Werror","-Wno-unused-function"]
        if os.environ.get("SPOTLESS_TEST_SANITIZE")=="1":
            command += ["-O1","-g","-fsanitize=address,undefined","-fno-omit-frame-pointer"]
        command += ['-DHOME="'+str(cls.home)+'"','-DCACHE="'+str(cls.cache)+'/"',str(ROOT/"tests/watcher_core.c"),"-o",str(cls.binary)]
        subprocess.run(command,check=True)
        record=(ROOT/"frontend/cache-analysis/spotifytv-record.original").read_bytes();m=decode_metadata(record)
        cls.source=record[m.body_offset:];cls.js=ROOT/"frontend/standalone/spotifytv.standalone.js"

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):
        for p in self.home.iterdir():p.unlink()
        for p in self.resource.iterdir():p.unlink()
        self.salt=b"new-salt";(self.cache/"salt").write_bytes(self.salt)
        self.record=self.resource/("B"*40)
        self.original=fixture(self.source,"https://tv.scdn.co/ps5/v2/f1b1b7e/js/spotifytv.js",self.salt)
        self.record.write_bytes(self.original);self.record.chmod(0o640)
        for letter,url in (("C","https://tv.scdn.co/ps5/v2/f1b1b7e/js/vendors.dabde9b04d44f0f634b7.js"),("D","https://tv.scdn.co/ps5/v2/f1b1b7e/css/spotifytv.css")):
            (self.resource/(letter*40)).write_bytes(fixture(b"nonempty asset",url,self.salt))

    def run_core(self,action,argument=None):
        return subprocess.run([str(self.binary),action,str(argument or self.js)],capture_output=True,text=True)

    def test_digest_reference_vectors_and_block_boundaries(self):
        path=self.root/"digest-input"
        for size in (1,3,55,56,63,64,65,127,128,129,10000):
            data=bytes(i%251 for i in range(size));path.write_bytes(data)
            for algorithm in ("sha1","sha256"):
                result=self.run_core(algorithm,path)
                self.assertEqual(result.returncode,0)
                self.assertEqual(result.stdout.strip(),getattr(hashlib,algorithm)(data).hexdigest())

    def test_readiness_waits_five_seconds_and_resets_on_changes(self):
        self.assertEqual(subprocess.run([str(self.binary),"ready"]).returncode,0)

    def test_native_rebuild_matches_reference_preserves_mode_and_is_idempotent(self):
        self.assertEqual(self.run_core("apply").returncode,0)
        expected=rebuild_record(self.original,self.js.read_bytes(),self.salt)
        self.assertEqual(self.record.read_bytes(),expected)
        self.assertEqual(self.record.stat().st_mode&0o777,0o640)
        inode=self.record.stat().st_ino;mtime=self.record.stat().st_mtime_ns
        self.assertEqual(self.run_core("apply").returncode,0)
        self.assertEqual((self.record.stat().st_ino,self.record.stat().st_mtime_ns),(inode,mtime))
        self.assertEqual((self.home/"original.record").read_bytes(),self.original)
        self.assertEqual(self.run_core("restore").returncode,0)
        self.assertEqual(self.record.read_bytes(),self.original)

    def test_utf16_metadata_and_different_salt(self):
        self.salt=b"salt-two";(self.cache/"salt").write_bytes(self.salt)
        self.original=fixture(self.source,"https://tv.scdn.co/ps5/v2/f1b1b7e/js/spotifytv.js",self.salt,wide=True)
        self.record.write_bytes(self.original)
        # Other assets must also validate against this console's salt.
        self.set_assets_for_salt()
        self.assertEqual(self.run_core("apply").returncode,0)
        self.assertEqual(self.record.read_bytes(),rebuild_record(self.original,self.js.read_bytes(),self.salt))

    def set_assets_for_salt(self):
        for letter,url in (("C","https://tv.scdn.co/ps5/v2/f1b1b7e/js/vendors.dabde9b04d44f0f634b7.js"),("D","https://tv.scdn.co/ps5/v2/f1b1b7e/css/spotifytv.css")):
            (self.resource/(letter*40)).write_bytes(fixture(b"asset",url,self.salt))

    def test_corruption_missing_assets_and_unknown_frontend_refused(self):
        for changed in (self.original[:-1],self.original[:-1]+bytes([self.original[-1]^1]),fixture(b"unknown frontend","https://tv.scdn.co/ps5/v2/f1b1b7e/js/spotifytv.js",self.salt)):
            self.record.write_bytes(changed)
            self.assertNotEqual(self.run_core("apply").returncode,0)
            self.assertEqual(self.record.read_bytes(),changed)
        self.record.write_bytes(self.original);(self.resource/("D"*40)).unlink()
        self.assertNotEqual(self.run_core("apply").returncode,0)
        self.assertFalse((self.home/"original.record").exists())

    def test_malformed_metadata_and_wrong_salt_never_write(self):
        cases=[self.original[:n] for n in (1,3,12,80,184)]
        for offset,value in ((0,17),(4,0x7fffffff)):
            changed=bytearray(self.original);struct.pack_into("<I",changed,offset,value);cases.append(bytes(changed))
        for changed in cases:
            self.record.write_bytes(changed)
            self.assertNotEqual(self.run_core("apply").returncode,0)
            self.assertFalse((self.home/"original.record").exists())
        self.record.write_bytes(self.original);(self.cache/"salt").write_bytes(b"bad-salt")
        self.assertNotEqual(self.run_core("apply").returncode,0)
        self.assertEqual(self.record.read_bytes(),self.original)

    def test_already_patched_detected_even_after_optional_assets_evicted(self):
        self.assertEqual(self.run_core("apply").returncode,0)
        (self.resource/("C"*40)).unlink();(self.resource/("D"*40)).unlink()
        inode=self.record.stat().st_ino
        scan=self.run_core("scan")
        self.assertEqual(scan.stdout.strip(),"0 2 0 0 1")
        self.assertEqual(self.record.stat().st_ino,inode)

    def test_duplicate_bundle_and_stale_backup_refused(self):
        duplicate=self.resource/("E"*40);duplicate.write_bytes(self.original)
        self.assertNotEqual(self.run_core("apply").returncode,0);duplicate.unlink()
        (self.home/"original.record").write_bytes(b"prior state")
        self.assertNotEqual(self.run_core("apply").returncode,0)
        self.assertEqual((self.home/"original.record").read_bytes(),b"prior state")
        self.assertEqual(self.record.read_bytes(),self.original)

    def test_restore_refuses_changed_live_record_and_path_escape(self):
        self.assertEqual(self.run_core("apply").returncode,0)
        self.record.write_bytes(b"unexpected live content")
        self.assertNotEqual(self.run_core("restore").returncode,0)
        self.assertEqual(self.record.read_bytes(),b"unexpected live content")
        (self.home/"record-path").write_bytes(b"/system_ex/other")
        self.assertNotEqual(self.run_core("restore").returncode,0)


if __name__=="__main__":unittest.main()
