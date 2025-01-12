# appModules\vlc\vlc_playlist.py
# a part of vlcAccessEnhancement add-on
# Copyright 2019-2020 paulber19
# This file is covered by the GNU General Public License.
# some ideas and code source comes from VLC add-on written by Javi Dominguez.


import addonHandler

import controlTypes
import api
import speech
import queueHandler
import eventHandler
import ui
import keyboardHandler
from NVDAObjects.IAccessible import IAccessible, qt
import time
import wx
import os
import oleacc
from IAccessibleHandler import accNavigate
from . import vlc_application
import sys
_curAddon = addonHandler.getCodeAddon()
debugToolsPath = os.path.join(_curAddon.path, "debugTools")
sys.path.append(debugToolsPath)
try:
	from appModuleDebug import printDebug, toggleDebugFlag
except ImportError:
	def prindDebug(msg): return
	def toggleDebugFlag(): return
del sys.path[-1]
sharedPath = os.path.join(_curAddon.path, "shared")
sys.path.append(sharedPath)
from vlc_utils import *  # noqa:F403,E402
from vlc_settingsHandler import *  # noqa:F403,E402
from vlc_py3Compatibility import rangeGen  # noqa:E402
del sys.path[-1]
addonHandler.initTranslation()

# Selection
msaa_SELFLAG_NONE = 0x00000000
msaa_SELFLAG_TAKEFOCUS = 0x00000001
msaa_SELFLAG_TAKESELECTION = 0x00000002
msaa_SELFLAG_EXTENDSELECTION = 0x00000004
msaa_SELFLAG_ADDSELECTION = 0x00000008
msaa_SELFLAG_REMOVESELECTION = 0x00000010
msaa_SELFLAG_VALID = 0x0000001F


def getColumnHeaderCount(oIA):
	(o, childID) = accNavigate(oIA, 0, oleacc.NAVDIR_FIRSTCHILD)
	count = 0
	while o.accRole(0) == oleacc.ROLE_SYSTEM_COLUMNHEADER:
		count = count+1
		try:
			(o, childID) = accNavigate(o, 0, oleacc.NAVDIR_NEXT)
		except:  # noqa:E722
			break
	return count


def _getActiveChild(obj):
	printDebug("_getActiveChild: %s, childCount = %s" % (controlTypes.roleLabels.get(obj.role), obj.childCount))  # noqa:E501
	# QT doesn't do accFocus properly, so find the active child ourselves.
	if obj.childCount == 0:
		return None
	child = None
	oIA = obj.IAccessibleObject
	step = 1
	if obj.role == controlTypes.ROLE_TREEVIEW:
		step = getColumnHeaderCount(oIA)
		if step > 1 and obj.childCount > 20000:
			speech.speakMessage(_("Please wait"))
	for i in rangeGen(0, obj.childCount, step):
		if i > 20000\
			and obj.role in [controlTypes.ROLE_TREEVIEW, controlTypes.ROLE_LIST]:
			break
		oldChild = child
		child = oIA.accChild(i+1)
		# my modification to remove an NVDA error
		if child is None:
			break
		try:
			states = child.accState(0)
		except:  # noqa:E722
			continue
		if states & oleacc.STATE_SYSTEM_FOCUSED\
			or states & oleacc.STATE_SYSTEM_SELECTED:
			return obj.getChild(i)
		# 9202: In Virtualbox 5.2 and above, accNavigate is severely broken,
		# returning the current object when calling next, causing an endless loop.
		if oldChild == child:
			break
	printDebug("_getActiveChild end with no child:i= %s" % i)
	return None


class InPlaylist(IAccessible):
	def event_focusEntered(self):
		pass


class InAnchoredPlaylist(InPlaylist):
	def initOverlayClass(self):
		self.inAnchoredPlaylist = True
		self.playlistSpoken = False

	def _get_activeChild(self):
		printDebug("InAnchoredPlaylist: _get_activeChild")
		return _getActiveChild(self)

	def event_gainFocus(self):
		printDebug("InAnchoredPlaylist: event_gainFocus: %s, isFocusable: %s, " % (controlTypes.roleLabels[self.role], self.isFocusable))  # noqa:E501
		# if it's first event_gainFocus in anchored playlist,
		# speak anchored playlist name
		previousFocus = self.appModule.lastFocusedObject
		if previousFocus is None:
			previousFocus = self
		if not hasattr(previousFocus, "inAnchoredPlaylist")\
			or not hasattr(previousFocus, "playlistSpoken")\
			or not previousFocus.playlistSpoken:
			queueHandler.queueFunction(
				queueHandler.eventQueue,
				speech.speakMessage, VLCAnchoredPlaylist._playlistName)
		self.playlistSpoken = True
		queueHandler.queueFunction(queueHandler.eventQueue, self.reportFocus)

	def script_hideShowPlaylist(self, gesture):
		mainPanel = self.appModule.mainWindow.mainPanel
		anchoredPlaylist = mainPanel.anchoredPlaylist
		if anchoredPlaylist.isAlive():
			anchoredPlaylist.reportViewState()


class InEmbeddedPlaylist(InPlaylist):
	def initOverlayClass(self):
		self.inAnchoredPlaylist = False
		self.playlistSpoken = False


class VLCQTContainer(qt.Container):
	def event_gainFocus(self):
		printDebug("VLCQTContainer: event_gainFocus")
		super(VLCQTContainer, self).event_gainFocus()

	def _get_activeChild(self):
		return _getActiveChild(self)

	def _get_shouldAllowIAccessibleFocusEvent(self):
		printDebug("VLCQTContainer: _get_shouldAllowIAccessibleFocusEvent")
		ret = super(VLCQTContainer, self)._get_shouldAllowIAccessibleFocusEvent()
		if not ret:
			# we don't where is the focus, so return to the top of tree view

			def moveUpAndDown():
				keyboardHandler.KeyboardInputGesture.fromName("upArrow").send()
				speech.cancelSpeech()
				keyboardHandler.KeyboardInputGesture.fromName("downArrow").send()
			wx.CallLater(300, moveUpAndDown)

		return ret


class VLCAnchoredPlaylistTreeView(InAnchoredPlaylist, VLCQTContainer):
	pass


class VLCEmbeddedPlaylistTreeView(InEmbeddedPlaylist, VLCQTContainer):
	pass


class VLCTreeViewItem(qt.TreeViewItem):
	def _get_states(self):
		states = super(VLCTreeViewItem, self)._get_states()
		# expanded state is useless
		states.discard(controlTypes.STATE_EXPANDED)
		return states


class VLCAnchoredPlaylistTreeViewItem(InAnchoredPlaylist, VLCTreeViewItem):
	pass


class VLCEmbeddedPlaylistTreeViewItem(InEmbeddedPlaylist, VLCTreeViewItem):
	pass


class VLCListItem(IAccessible):
	def script_nextItem(self, gesture):
		self.selectItem(self.simpleNext)

	def script_previousItem(self, gesture):
		self.selectItem(self.simplePrevious)

	def selectItem(self, item):
		if item:
			item.scrollIntoView()
			api.setNavigatorObject(item)
			api.moveMouseToNVDAObject(item)
			x, y = winUser.getCursorPos()
			if api.getDesktopObject().objectFromPoint(x, y) == item:
				winUser.mouse_event(winUser.MOUSEEVENTF_LEFTDOWN, 0, 0, None, None)
				winUser.mouse_event(winUser.MOUSEEVENTF_LEFTUP, 0, 0, None, None)
				time.sleep(0.1)
				eventHandler.queueEvent("gainFocus", item)
				return
				item.setFocus()
				api.setFocusObject(item)
				if item.name:
					ui.message(item.name)
			else:
				pass

	__gestures = {
		"kb:downArrow": "nextItem",
		"kb:upArrow": "previousItem",
	}


class VLCAnchoredPlaylistListItem(InAnchoredPlaylist, VLCListItem):
	pass


class VLCEmbeddedPlaylistListItem(InEmbeddedPlaylist, VLCListItem):
	pass


class VLCEmbeddedPlaylist(InEmbeddedPlaylist):
	pass


class VLCAnchoredPlaylist(InAnchoredPlaylist):
	# Translators: name of anchored playlist panel.
	_playlistName = _("Anchored playlist")

	def _get_name(self):
		return self._playlistName


class VLCGroupTreeViewItem(qt.TreeViewItem):
	def reportFocus(self):
		self.playlist.reportGroupButtonName()

	def script_selectionChange(self, gesture):
		queueHandler.queueFunction(queueHandler.eventQueue, gesture.send)
		queueHandler.queueFunction(
			queueHandler.eventQueue,
			keyboardHandler.KeyboardInputGesture.fromName("Enter").send)

	__gestures = {
		"kb:downArrow": "selectionChange",
		"kb:upArrow": "selectionChange",
		"kb:home": "selectionChange",
		"kb:end": "selectionChange",
	}


class VLCAnchoredGroupTreeViewItem(InAnchoredPlaylist, VLCGroupTreeViewItem):
	def initOverlayClass(self):
		mainPanel = self.appModule.mainWindow.mainPanel
		self.playlist = mainPanel.anchoredPlaylist


class VLCEmbeddedGroupTreeViewItem(InEmbeddedPlaylist, VLCGroupTreeViewItem):
	def initOverlayClass(self):
		self.playlist = vlc_application.EmbeddedPlaylist()
