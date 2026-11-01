import os
import unittest
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from everstickynote.single_instance import SingleInstance, notify_running


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _app()

    def setUp(self):
        self.name = f"EverStickyNoteTest-{uuid.uuid4().hex}"
        self.instances: list[SingleInstance] = []

    def tearDown(self):
        for instance in self.instances:
            instance.release()

    def _instance(self) -> SingleInstance:
        instance = SingleInstance(self.name)
        self.instances.append(instance)
        return instance

    def test_only_the_first_instance_acquires(self):
        self.assertTrue(self._instance().acquire())
        self.assertFalse(self._instance().acquire())

    def test_second_launch_tells_the_first_to_show(self):
        first = self._instance()
        self.assertTrue(first.acquire())
        calls: list[bool] = []
        first.activated.connect(lambda: calls.append(True))
        self.assertTrue(notify_running(self.name))
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(20)
        timer.timeout.connect(lambda: loop.quit() if calls else None)
        QTimer.singleShot(3000, loop.quit)
        timer.start()
        loop.exec()
        timer.stop()
        self.assertEqual(calls, [True])

    def test_name_is_free_again_after_release(self):
        first = self._instance()
        self.assertTrue(first.acquire())
        first.release()
        self.assertFalse(notify_running(self.name))
        self.assertTrue(self._instance().acquire())


if __name__ == "__main__":
    unittest.main()
