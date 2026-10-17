"""Host browser receipt binding; these tests do not claim browser execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

spec=importlib.util.spec_from_file_location('review',Path(__file__).resolve().parents[1]/'benchmarks/market-blind/browser_review.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class BrowserReviewTests(unittest.TestCase):
    def test_ready_signal_and_immediate_bound_receipt_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);work=folder/'work';work.mkdir();page=work/'index.html';page.write_text('page')
            queue=folder/'review';queue.mkdir(mode=0o700);result=[]
            worker=threading.Thread(target=lambda:result.append(module.review(
                {'project_root':str(work)},queue,{'path':'index.html'},timeout=2)))
            worker.start()
            ready=module.await_request(queue,timeout=1)
            started=time.time()
            evidence={**ready,'status':'passed','executor':'root_cua',
                      'review_started_at':started,'review_finished_at':time.time(),
                      'checks':{key:True for key in ready['required_checks']}}
            module.complete_review(queue,evidence)
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result[0]['status'],'passed')
            timing=json.loads((queue/'timing.json').read_text())
            self.assertLessEqual(timing['host_observed_at'],timing['review_started_at'])
            self.assertLessEqual(timing['published_at'],timing['gateway_received_at'])
            self.assertLess(timing['gateway_received_at']-timing['published_at'],.5)
            with self.assertRaises(FileExistsError):module.complete_review(queue,evidence)
            with self.assertRaises(FileExistsError):module.await_request(queue,timeout=.1)

    def test_publisher_rejects_wrong_or_incomplete_evidence_and_changed_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);page=folder/'index.html';page.write_text('page')
            request={'id':'one','artifact':str(page),'sha256':module.digest(page),'created_at':time.time(),
                     'required_checks':['formula','sliders','reset','clipboard']}
            module.publish_once(folder/'request.json',request)
            complete={**request,'status':'passed','executor':'root_cua',
                      'checks':{key:True for key in request['required_checks']}}
            for change in ({'id':'old'},{'sha256':'wrong'},{'checks':{}},{'executor':'simulated'}):
                with self.subTest(change=change),self.assertRaises(ValueError):
                    module.complete_review(folder,{**complete,**change})
                self.assertFalse((folder/'response.json').exists())
            page.write_text('changed')
            with self.assertRaisesRegex(ValueError,'artifact_changed'):module.complete_review(folder,complete)
            with self.assertRaisesRegex(ValueError,'artifact_changed'):module.await_request(folder,.1)

    def test_ready_deadline_does_not_create_or_accept_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            with self.assertRaises(TimeoutError):module.await_request(folder,.01)
            self.assertEqual(list(folder.iterdir()),[])

    def test_late_observer_does_not_restart_expired_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);page=folder/'index.html';page.write_text('page')
            request={'id':'expired','artifact':str(page),'sha256':module.digest(page),
                     'created_at':time.time()-1,'expires_at':time.time()-.1}
            module.publish_once(folder/'request.json',request)
            with self.assertRaisesRegex(TimeoutError,'expired'):module.await_request(folder,.1)
            self.assertFalse((folder/'host-ready.json').exists())
            self.assertFalse((folder/'response.json').exists())

    def test_explicit_matching_browser_receipt_and_changed_artifact(self):
        for changed in (False,True):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);work=folder/'work';work.mkdir();page=work/'index.html';page.write_text('original')
                queue=folder/'review';queue.mkdir(mode=0o700)
                def evaluator():
                    while not (queue/'request.json').exists():time.sleep(.005)
                    # Request creation can precede its complete write.
                    while True:
                        try:request=json.loads((queue/'request.json').read_text());break
                        except ValueError:time.sleep(.005)
                    if changed:page.write_text('changed')
                    value={**request,'status':'passed','executor':'root_cua',
                           'checks':{key:True for key in request['required_checks']}}
                    temp=queue/'response.tmp';temp.write_text(json.dumps(value));temp.replace(queue/'response.json')
                thread=threading.Thread(target=evaluator);thread.start()
                if changed:
                    with self.assertRaisesRegex(ValueError,'artifact_changed'):
                        module.review({'project_root':str(work)},queue,{'path':'index.html'},timeout=1)
                else:self.assertEqual(module.review({'project_root':str(work)},queue,{'path':str(page)},timeout=1)['status'],'passed')
                thread.join()

    def test_timeout_is_not_a_pass_or_an_automatic_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'index.html').write_text('page')
            result=module.review({'project_root':str(folder)},folder,{'path':'index.html'},timeout=.01)
            self.assertEqual(result['status'],'unavailable')
            with self.assertRaises(FileExistsError):
                module.review({'project_root':str(folder)},folder,{'path':'index.html'},timeout=.01)

    def test_outside_path_never_creates_a_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('../index.html','/tmp/index.html','auth.json'):
                with self.assertRaises(ValueError):module.review({'project_root':tmp},Path(tmp),{'path':name})
            self.assertFalse((Path(tmp)/'request.json').exists())
