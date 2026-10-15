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
