import functools
import logging
import operator
import os
import re
import sys
from collections import namedtuple
from contextlib import contextmanager

import Qt
from Qt import QtCompat, QtCore, QtGui, QtWidgets
from Qt.QtGui import QTextBlockFormat as QTBF
from Qt.QtGui import QTextCharFormat as QTCF
from Qt.QtGui import QTextCursor as QTC

DEFAULT_MESSAGE_TIMEOUT = 5000
ORG_NAME = "Adhi Hargo"
APP_NAME = "PyRegexTest"

GroupingAction = namedtuple("GroupingAction", ["text", "paste_pos", "cursor_pos", "min_py_ver"])
SpanInfo = namedtuple("SpanInfo", ["char_fmt", "start_pos", "end_pos"])

logger = logging.getLogger(APP_NAME)


def get_exec_func(obj):
    exec_func = next((f_obj for f_name in ["exec", "exec_"]
                      for f_obj in (getattr(obj, f_name, None), ) if f_obj is not None), None)
    return exec_func


def leftrot(x, d):
    return (x << (8 * (d % 3)))


def get_color(idx=0, offset=0):
    cycle_idx, cycle_num = divmod(idx, 6)
    base_val = 0x000020 + (0x20 * offset)
    cycle_val = 0x10 * cycle_idx
    add_val = cycle_val | leftrot(cycle_val, 1) | leftrot(cycle_val, 2)

    shift = idx % 3
    val = leftrot(base_val, shift)
    if cycle_num > 2:
        val |= leftrot(base_val, shift + 1)
    val += add_val
    val ^= 0xffffff

    return val


@contextmanager
def blockSignals(wdg, value=True):
    wdg.blockSignals(value)
    yield
    wdg.blockSignals(False)


class MainWindow(QtWidgets.QMainWindow):

    @property
    def regex_text(self):
        return self.txeRegex.toPlainText()

    @property
    def replace_text(self):
        return self.lneReplace.text()

    @property
    def input_text(self):
        return self.txeSampleInput.toPlainText()

    @property
    def regex_flags(self):
        return functools.reduce(operator.or_, self.__regex_flags, 0)

    def __init__(self, parent=None):
        super(MainWindow, self).__init__()
        uiFile = os.path.join(os.path.dirname(__file__), "res", "main.ui")
        ui = QtCompat.loadUi(uifile=uiFile, baseinstance=self)
        self.setWindowTitle("PyRegexTest")
        self.__regex_obj = None
        self.__regex_flags = set()
        self.__settings = QtCore.QSettings(ORG_NAME, APP_NAME)
        self.__flag_mapping = {
            getattr(self, "chbIgnoreCase", None): re.IGNORECASE,
            getattr(self, "chbMultiLine", None): re.MULTILINE,
            getattr(self, "chbDotAll", None): re.DOTALL,
            getattr(self, "chbVerbose", None): re.VERBOSE
        }

        self.default_char_fmt = self.txeRegex.textCursor().charFormat()
        self.error_char_fmt = QTCF()
        self.error_char_fmt.setBackground(QtGui.QBrush(QtCore.Qt.red))
        self.match_char_fmt_list = [QTCF() for _ in range(2)]
        for idx, fmt in enumerate(self.match_char_fmt_list):
            fmt.setBackground(QtGui.QColor(0xf0f0f0 - (0x202020 * idx)))
            fmt.setFontUnderline(True)
        self.txeRegex.setPlainText("")

        self.__context_menu = QtWidgets.QMenu(self)
        self.__init_context_menu()

        font = QtGui.QFont("courier")
        font.setFixedPitch(True)
        font.setStyleHint(QtGui.QFont.TypeWriter)
        font.setPointSize(font.pointSize() + 1)
        font_metrics = QtGui.QFontMetrics(font)
        tab_width = font_metrics.horizontalAdvance(" ", len=4)
        for wdg in [
                self.txeRegex, self.lneReplace, self.txeSampleInput, self.txeSearchResult,
                self.txeReplaceResult
        ]:
            wdg.setFont(font)
            wdg.setProperty("tabStopDistance", tab_width)

        for chb in [self.chbIgnoreCase, self.chbMultiLine, self.chbDotAll, self.chbVerbose]:
            chb.toggled.connect(self.on_flagChange)

        self.read_settings()
        self.txeRegex.setFocus()

    def __init_context_menu(self):
        for name, data in [
            ("Grouping: Standa&rd", GroupingAction("()", 1, -1, None)),
            ("Grouping: &Named", GroupingAction("(?P<>)", 5, 4, None)),
            ("Grouping: Non-&capturing", GroupingAction("(?:)", 3, -1, None)),
            ("Grouping: A&tomic", GroupingAction("(?>)", 3, -1, (3, 11))),
            ("Grouping: &Backreference", GroupingAction("(?P=)", 4, -1, None)),
            ("Grouping: Positive &lookahead", GroupingAction("(?=)", 3, -1, None)),
            ("Grouping: N&egative lookahead", GroupingAction("(?!)", 3, -1, None)),
            ("Grouping: Po&sitive lookbehind", GroupingAction("(?<=)", 4, -1, None)),
            ("Grouping: Neg&ative lookbehind", GroupingAction("(?<!)", 4, -1, None)),
            ("Grouping: Con&ditional", GroupingAction("(?())", 4, 3, None)),
        ]:
            if (data.min_py_ver > (sys.version_info[0], sys.version_info[1])) if data.min_py_ver else False:
                continue
            act = self.__context_menu.addAction(name)
            act.setData(data)
            act.triggered.connect(self.on_txeRegex_contextAction)

    def update_regex_test(self):
        self.__update_regex_obj()
        self.__update_search_result()
        self.__update_replace_result()

    def __update_regex_obj(self):
        try:
            self.__regex_obj = re.compile(self.regex_text, self.regex_flags)
            if not self.lblRegexStatus.valid_regex:
                self.__clear_error_mark()
                self.lblRegexStatus.valid_regex = True
            self.statusBar().clearMessage()
        except re.error as exc:
            self.__regex_obj = None
            self.__mark_error(exc.lineno, exc.colno)

            error_str = self.__get_regex_exc(exc)
            self.statusBar().showMessage(error_str)
            self.lblRegexStatus.valid_regex = False

    def __update_search_result(self):
        input_text = self.input_text
        char_fmt_var_count = len(self.match_char_fmt_list)

        match_obj = None
        self.txeSearchResult.setPlainText(input_text)
        if self.__regex_obj and input_text:
            text_cur = self.txeSearchResult.textCursor()
            span_list = []
            for match_idx, match_obj in enumerate(self.__regex_obj.finditer(input_text)):
                start_pos, end_pos = match_obj.span()
                char_fmt = self.match_char_fmt_list[match_idx % char_fmt_var_count]
                span_list.append(SpanInfo(char_fmt, start_pos, end_pos))
                for group_idx, group_str in enumerate(match_obj.groups(), start=1):
                    start_pos, end_pos = match_obj.start(group_idx), match_obj.end(group_idx)
                    if start_pos < 0 or end_pos < 0:  # skip empty group
                        continue
                    char_fmt = self.group_char_fmt(group_idx, offset=match_idx % 2)
                    span_list.append(SpanInfo(char_fmt, start_pos, end_pos))

            text_cur.movePosition(QTC.Start)
            for span_info in span_list:
                text_cur.setPosition(span_info.start_pos)
                text_cur.setPosition(span_info.end_pos, QTC.KeepAnchor)

                text_cur.mergeCharFormat(span_info.char_fmt)
                text_cur.clearSelection()
                text_cur.setCharFormat(self.default_char_fmt)
            self.txeSearchResult.setTextCursor(text_cur)

    def __update_replace_result(self):
        replace_text = self.replace_text

        if self.__regex_obj and self.regex_text and replace_text:
            replace_result_text = self.__regex_obj.sub(replace_text, self.input_text)
            self.txeReplaceResult.setPlainText(replace_result_text)
        else:
            self.txeReplaceResult.clear()

    def __get_regex_exc(self, exc: re.error):
        if exc.lineno is not None:
            if exc.colno is not None:
                prefix_str = "[{}, {}] ".format(exc.lineno, exc.colno)
            else:
                prefix_str = "[{}] ".format(exc.lineno)
        else:
            prefix_str = ""

        return "{}{}".format(prefix_str, exc.msg)

    def __clear_error_mark(self):
        text_cur = self.txeRegex.textCursor()
        with blockSignals(self.txeRegex):
            text_pos = text_cur.position()
            text_cur.select(QTC.Document)
            text_cur.setCharFormat(self.default_char_fmt)
            text_cur.clearSelection()
            text_cur.setPosition(text_pos)
            self.txeRegex.setTextCursor(text_cur)

    def __mark_error(self, lineno, colno):
        if lineno is None or colno is None:
            return
        with blockSignals(self.txeRegex):
            text_cur = self.txeRegex.textCursor()
            prev_pos = text_cur.position()
            text_cur.movePosition(QTC.Start)
            text_cur.movePosition(QTC.Down, n=lineno)
            text_cur.movePosition(QTC.Right, n=colno)
            text_cur.movePosition(QTC.Left, QTC.KeepAnchor)

            text_cur.mergeCharFormat(self.error_char_fmt)
            text_cur.setPosition(prev_pos)
            text_cur.setCharFormat(self.default_char_fmt)

            self.txeRegex.setTextCursor(text_cur)

    @functools.lru_cache()
    def group_char_fmt(self, idx, offset=0):
        char_fmt = QTCF()
        color = get_color(idx, offset)
        char_fmt.setBackground(QtGui.QColor(color))
        return char_fmt

    def read_settings(self):
        regex_text = self.__settings.value("regex_text", None)
        input_text = self.__settings.value("input_text", None)
        replace_text = self.__settings.value("replace_text", None)
        regex_flags = self.__settings.value("regex_flags", None)

        if regex_text:
            self.txeRegex.setPlainText(regex_text)
        if input_text:
            self.txeSampleInput.setPlainText(input_text)
        if replace_text:
            self.lneReplace.setText(replace_text)
        if regex_flags:
            for wdg, flag in self.__flag_mapping.items():
                wdg.setChecked(flag & regex_flags)

    def write_settings(self):
        self.__settings.setValue("regex_text", self.regex_text)
        self.__settings.setValue("replace_text", self.replace_text)
        self.__settings.setValue("input_text", self.input_text)
        self.__settings.setValue("regex_flags", int(self.regex_flags))

    @QtCore.Slot()
    def on_txeRegex_textChanged(self):
        self.update_regex_test()

    @QtCore.Slot(QtCore.QPoint)
    def on_txeRegex_customContextMenuRequested(self, pos):
        menu_exec_func = get_exec_func(self.__context_menu)
        menu_exec_func(self.txeRegex.mapToGlobal(pos))

    def on_txeRegex_contextAction(self, *args, **kwargs):
        data = self.sender().data()
        text_cur = self.txeRegex.textCursor()
        sel_text = text_cur.selectedText()

        text_cur.beginEditBlock()
        text_cur.removeSelectedText()
        text_pos = text_cur.position()
        text_cur.insertText(data.text)
        text_cur.setPosition(text_pos)  #return
        text_cur.movePosition(QTC.Right, n=data.paste_pos)
        text_cur.insertText(sel_text)  # reinsert selection
        cursor_pos = data.cursor_pos
        if cursor_pos >= 0:
            text_cur.setPosition(text_pos)
            text_cur.movePosition(QTC.Right, n=cursor_pos)
        else:
            text_cur.movePosition(QTC.Left, QTC.KeepAnchor, n=len(sel_text))
        text_cur.endEditBlock()
        self.txeRegex.setTextCursor(text_cur)

    @QtCore.Slot()
    def on_lneReplace_textChanged(self):
        self.update_regex_test()

    @QtCore.Slot()
    def on_txeSampleInput_textChanged(self):
        self.update_regex_test()

    def on_flagChange(self, value):
        sender = QtCore.QObject.sender(self)
        flag = self.__flag_mapping.get(sender)
        if flag:
            if value:
                self.__regex_flags.add(flag)
            else:
                self.__regex_flags.discard(flag)

        self.update_regex_test()

    @QtCore.Slot()
    def on_actEditCopyToClipboard_triggered(self):
        text = self.regex_text
        clipboard = QtWidgets.QApplication.clipboard()
        if text:
            clipboard.setText(text)

    def closeEvent(self, event):
        self.write_settings()
        event.accept()


class StatusText(QtWidgets.QLabel):
    css_valid = "color: rgb(255, 255, 255);\nbackground-color: rgb(0, 0, 255);"
    css_invalid = "color: rgb(255, 255, 255);\nbackground-color: rgb(255, 0, 0);"

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.__valid_regex__ = False

    @property
    def valid_regex(self):
        return self.__valid_regex__

    @valid_regex.setter
    def valid_regex(self, value: bool):
        if value == self.__valid_regex__:
            return

        self.__valid_regex__ = value
        self.__set_regex_ui__(value)

    def __set_regex_ui__(self, value):
        self.setText("VALID" if value else "INVALID")
        self.setStyleSheet(self.css_valid if value else self.css_invalid)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(sys.argv)
    ui = MainWindow()
    ui.show()

    exec_func = get_exec_func(app)
    if exec_func:
        exec_func()
    else:
        print("Python Qt execution function not found.")
