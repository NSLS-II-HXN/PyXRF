from PyQt5.QtWidgets import (QLineEdit, QWidget, QHBoxLayout, QComboBox, QTextEdit,
                             QSizePolicy, QLabel, QPushButton, QGridLayout, QSlider)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QFontMetrics

global_gui_parameters = {
    "vertical_spacing_in_tabs": 5
}

global_gui_variables = {
    # Reference to main window
    "ref_main_window": None,
    # The flags that control current GUI state
    # (global state that determines if elements are enabled/visible)
    "gui_state": {
        "databroker_available": False,
        "running_computations": False,
        # The following states are NOT mutually exclusive
        "state_file_loaded": False,
        "state_model_exist": False,
        "state_model_fit_exists": False,
        "state_xrf_map_exists": False,
    },
    # Indicates if tooltips must be shown
    "show_tooltip": True,
    "show_matplotlib_toolbar": True
}


def clear_gui_state(gui_vars):
    """
    Clear GUI state. Reset the variables that determine GUI state.
    This should be done before the new data is loaded from file or from Databoker.
    The variables are set so that the state of GUI is "No data is loaded"

    Parameters
    ----------
    gui_vars: dict
        reference to the dictionary `global_gui_variables`
    """
    gui_vars["gui_state"]["state_file_loaded"] = False
    gui_vars["gui_state"]["state_model_exist"] = False
    gui_vars["gui_state"]["state_model_fit_exists"] = False
    gui_vars["gui_state"]["state_xrf_map_exists"] = False


def set_tooltip(widget, text):
    """
    Set tooltips for the widget. Use global variable `global_gui_variables["show_tooltips"]`
    to determine if tooltips must be set.

    Parameters
    ----------
    widget: QWidget
        reference to the widget
    text: str
        text to set as a tooltip
    """
    if not global_gui_variables["show_tooltip"]:
        text = ""
    widget.setToolTip(text)


class LineEditReadOnly(QLineEdit):
    """
    Read-only version of QLineEdit with background set to the same color
    as the background of the disabled QLineEdit, but font color the same
    as active QLineEdit.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        # Set background color the same as for disabled window.
        p = self.palette()
        p.setColor(QPalette.Base, p.color(QPalette.Disabled, QPalette.Base))
        self.setPalette(p)


class TextEditReadOnly(QTextEdit):
    """
    Read-only version of QTextEdit with background set to the same color
    as the background of the disabled QLineEdit, but font color the same
    as active QLineEdit.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setReadOnly(True)
        # Set background color the same as for disabled window.
        p = self.palette()
        p.setColor(QPalette.Base, p.color(QPalette.Disabled, QPalette.Base))
        self.setPalette(p)


class PushButtonMinimumWidth(QPushButton):
    """
    Push button with text ".." and minimum width
    """
    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        text = self.text()
        font = self.font()

        fm = QFontMetrics(font)
        text_width = fm.width(text) + 6
        self.setFixedWidth(text_width)


class SecondaryWindow(QWidget):
    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # The variable indicates if the window was moved using 'position_once' function
        self._never_positioned = True

    def position_once(self, x, y, *, x_shift=30, y_shift=30, force=False):
        """
        Move the window once (typically before it is first shown).
        Used to position the window regarding the parent window before it is show.
        Then the user may move the window anywhere on the screen and it will remain
        there.

        Parameters
        ----------
        x, y: int
            screen coorinates of the left top corner of the parent window
        x_shift, y_shift: int
            shift applied to 'x' and 'y' to position left top corner of this window:
            the window is positioned at (x+x_shift, y+y_shift)
        force: bool
            True - move anyway, False (default) - move only the first time the function is called
        """
        if self._never_positioned or force:
            self._never_positioned = False
            self.move(x + x_shift, y + y_shift)


def adjust_qlistwidget_height(list_widget, *, other_widgets=None, min_height=40):
    """
    Adjust the height of QListWidget so that it fits the items exactly.
    If the computed height is smaller than `min_height`, then the height
    is set to `min_height`. If the list is empty, then the height is set
    to `min_height` (for pleasing look).

    The width of the widget is still adjusted automatically.
    Call this function each time the number of items in the list
    is changed.

    Parameters
    ----------
    list_widget: QListWidget
        reference to the list widget that needs to be adjusted.
    min_height: int
        minimum height of the widget.
    """

    if other_widgets is None:
        other_widgets = []

    # Compute and set the height of the list
    height = 0
    n_list_elements = list_widget.count()
    if n_list_elements:
        # Compute the height necessary to accommodate all the elements
        height = list_widget.sizeHintForRow(0) * n_list_elements + \
                2 * list_widget.frameWidth() + 3
    # Set some visually pleasing height if the list contains no elements
    height = max(height, min_height)
    list_widget.setMinimumHeight(height)
    list_widget.setMaximumHeight(height)

    # Now update size of the other ('parent') widgets
    for w in other_widgets:
        w.adjustSize()
        w.updateGeometry()  # This is necessary in some cases


def get_background_css(rgb, widget="QWidget", editable=False):
    """Returns the string that contain CSS to set widget background to specified color"""

    rgb = tuple(rgb)
    if len(rgb) != 3:
        raise ValueError(r"RGB must be represented by 3 elements: rgb = {rgb}")
    if any([(_ > 255) or (_ < 0) for _ in rgb]):
        raise ValueError(r"RGB values must be in the range 0..255: rgb={rgb}")

    # Shaded widgets appear brighter, so the brightness needs to be reduced
    shaded_widgets = ("QComboBox", "QPushButton")
    if widget in shaded_widgets:
        rgb = [max(int(255 - (255 - _) * 1.5), 0) for _ in rgb]

    # Increase brightness of editable element
    if editable:
        rgb = [255 - int((255 - _) * 0.5) for _ in rgb]

    color_css = f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
    return f"{widget} {{ background-color: {color_css}; }}"


class RangeManager(QWidget):
    """ Width of the widgets can be set using `setMaximumWidth`. The size policy is set
    so that the widget may shrink if there is not enough space."""

    def __init__(self, *, add_sliders=False):
        super().__init__()

        max_element_width = 200

        self.le_min_value = QLineEdit()
        self.le_max_value = QLineEdit()

        self.le_min_value.setMaximumWidth(max_element_width)
        self.le_max_value.setMaximumWidth(max_element_width)

        self.le_min_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.le_max_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.sld_min_value = QSlider(Qt.Horizontal)
        self.sld_max_value = QSlider(Qt.Horizontal)

        self.sld_min_value.setMaximumWidth(max_element_width)
        self.sld_max_value.setMaximumWidth(max_element_width)

        # The slider for controlling minimum is inverted
        self.sld_min_value.setInvertedAppearance(True)
        self.sld_min_value.setInvertedControls(True)

        # Set the maximum number of steps for the sliders (resolution)
        self.sld_n_steps = 10000
        self.sld_min_value.setMaximum(self.sld_n_steps - 1)
        self.sld_max_value.setMaximum(self.sld_n_steps - 1)

        self.sld_min_value.setValue(self.sld_min_value.maximum())
        self.sld_max_value.setValue(self.sld_max_value.maximum())

        grid = QGridLayout()
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.le_min_value, 0, 0)
        grid.addWidget(QLabel(".."), 0, 1)
        grid.addWidget(self.le_max_value, 0, 2)

        if add_sliders:
            grid.addWidget(self.sld_min_value, 1, 0)
            grid.addWidget(QLabel(""), 1, 1)
            grid.addWidget(self.sld_max_value, 1, 2)

        self.setLayout(grid)

        sp = QSizePolicy()
        sp.setControlType(QSizePolicy.PushButton)
        sp.setHorizontalPolicy(QSizePolicy.Maximum)
        self.setSizePolicy(sp)

    def setAlignment(self, flags):
        """
        Set text alignment in QLineEdit widgets

        Parameters
        ----------
        flags: Qt.Alignment flags
            flags that set alignment of text in QLineEdit widgets
            For example `Qt.AlignCenter`. The default settings
            for the widget is `Qt.AlignRight | Qt.AlignVCenter`.
        """

        self.le_min_value.setAlignment(flags)
        self.le_max_value.setAlignment(flags)

    def setBackground(self, rgb):
        """
        Set background color of the widget. Similar to QTableWidgetItem.setBackground,
        but accepting a tuple of RGB values instead of QBrush.

        Parameters
        ----------
        rgb: tuple(int)
            RGB color in the form of (R, G, B)
        """
        self.setStyleSheet(
            get_background_css(rgb, widget="QWidget", editable=False))

        self.le_min_value.setStyleSheet(
            get_background_css(rgb, widget="QLineEdit", editable=True))
        self.le_max_value.setStyleSheet(
            get_background_css(rgb, widget="QLineEdit", editable=True))


class ElementSelection(QWidget):
    """ Width of the widgets can be set using `setMaximumWidth`. The size policy is set
    so that the widget may shrink if there is not enough space."""

    def __init__(self):
        super().__init__()

        self.cb_element_list = QComboBox()
        self.setMaximumWidth(300)
        self.pb_prev = PushButtonMinimumWidth("<")
        self.pb_next = PushButtonMinimumWidth(">")

        hbox = QHBoxLayout()
        hbox.setSpacing(0)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.addWidget(self.pb_prev)
        hbox.addWidget(self.cb_element_list)
        hbox.addWidget(self.pb_next)

        self.setLayout(hbox)

        sp = QSizePolicy()
        sp.setControlType(QSizePolicy.PushButton)
        sp.setHorizontalPolicy(QSizePolicy.Maximum)
        self.setSizePolicy(sp)

    def addItems(self, items):
        self.cb_element_list.addItems(items)

    def addItem(self, item):
        self.cb_element_list.addItem(item)


"""
class LineEditWithSlider(QLineEdit):
    def __init__(self):
        super().__init__()
        self.wd_slider = QWidget(self)

    #def mousePressEvent(self, event):
    #    import random
    #    print(f"'LineEditWithSlider': mouse pressed {random.random()}")
    #    if event.button() == Qt.LeftButton:
    #        print(f"Left button was pressed {random.random()}")

    def focusInEvent(self, event):
        import random
        print(f"'LineEditWithSlider': focus in {random.random()}")

        fg = self.frameGeometry()
        self.wd_slider.setGeometry(fg)
        self.wd_slider.move(fg.x(), fg.y() + fg.height())
        self.wd_slider.show()


    def focusOutEvent(self, event):
        import random
        print(f"'LineEditWithSlider': focus out {random.random()}")

"""
"""
MAXVAL = 650000

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLayout, QFrame, QSlider
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QSize, QMetaObject, pyqtSlot

class RangeSliderClass(QWidget):

    def __init__(self):
        super().__init__()

        self.minTime = 0
        self.maxTime = 0
        self.minRangeTime = 0
        self.maxRangeTime = 0

        self.sliderMin = MAXVAL
        self.sliderMax = MAXVAL

        self.setupUi(self)

    def setupUi(self, RangeSlider):
        RangeSlider.setObjectName("RangeSlider")
        RangeSlider.resize(1000, 65)
        RangeSlider.setMaximumSize(QSize(16777215, 65))
        self.RangeBarVLayout = QVBoxLayout(RangeSlider)
        self.RangeBarVLayout.setContentsMargins(5, 0, 5, 0)
        self.RangeBarVLayout.setSpacing(0)
        self.RangeBarVLayout.setObjectName("RangeBarVLayout")

        self.slidersFrame = QFrame(RangeSlider)
        self.slidersFrame.setMaximumSize(QSize(16777215, 25))
        self.slidersFrame.setFrameShape(QFrame.StyledPanel)
        self.slidersFrame.setFrameShadow(QFrame.Raised)
        self.slidersFrame.setObjectName("slidersFrame")
        self.horizontalLayout = QHBoxLayout(self.slidersFrame)
        self.horizontalLayout.setSizeConstraint(QLayout.SetMinimumSize)
        self.horizontalLayout.setContentsMargins(5, 2, 5, 2)
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setObjectName("horizontalLayout")

        ## Start Slider Widget
        self.startSlider = QSlider(self.slidersFrame)
        self.startSlider.setMaximum(self.sliderMin)
        self.startSlider.setMinimumSize(QSize(100, 5))
        self.startSlider.setMaximumSize(QSize(16777215, 10))

        font = QFont()
        font.setKerning(True)

        self.startSlider.setFont(font)
        self.startSlider.setAcceptDrops(False)
        self.startSlider.setAutoFillBackground(False)
        self.startSlider.setOrientation(Qt.Horizontal)
        self.startSlider.setInvertedAppearance(True)
        self.startSlider.setObjectName("startSlider")
        self.startSlider.setValue(MAXVAL)
        self.startSlider.valueChanged.connect(self.handleStartSliderValueChange)
        self.horizontalLayout.addWidget(self.startSlider)

        ## End Slider Widget
        self.endSlider = QSlider(self.slidersFrame)
        self.endSlider.setMaximum(MAXVAL)
        self.endSlider.setMinimumSize(QSize(100, 5))
        self.endSlider.setMaximumSize(QSize(16777215, 10))
        self.endSlider.setTracking(True)
        self.endSlider.setOrientation(Qt.Horizontal)
        self.endSlider.setObjectName("endSlider")
        self.endSlider.setValue(self.sliderMax)
        self.endSlider.valueChanged.connect(self.handleEndSliderValueChange)

        #self.endSlider.sliderReleased.connect(self.handleEndSliderValueChange)

        self.horizontalLayout.addWidget(self.endSlider)

        self.RangeBarVLayout.addWidget(self.slidersFrame)

        #self.retranslateUi(RangeSlider)
        QMetaObject.connectSlotsByName(RangeSlider)

        self.show()

    @pyqtSlot(int)
    def handleStartSliderValueChange(self, value):
        self.startSlider.setValue(value)

    @pyqtSlot(int)
    def handleEndSliderValueChange(self, value):
        self.endSlider.setValue(value)
"""