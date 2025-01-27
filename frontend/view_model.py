import spotify_manager
import system_controller
from functools import lru_cache
from config import *
import os
import threading
import queue
import re as re

# Screen render types
MENU_RENDER_TYPE = 0
NOW_PLAYING_RENDER = 1
SEARCH_RENDER = 2
BOOT_RENDER = 3

SystemController = system_controller.SystemController()
Bluetoothctl = system_controller.Bluetoothctl()
Audioctl = system_controller.Audioctl()
#spotify_manager.refresh_data()

class LineItem():
    def __init__(self, title = "", line_type = LINE_NORMAL, show_arrow = False, selectable = True, value = None):
        self.title = title
        self.line_type = line_type
        self.show_arrow = show_arrow
        self.selectable = selectable
        self.value = value

class Rendering():
    def __init__(self, type):
        self.type = type

    def unsubscribe(self):
        pass

class BootRendering(Rendering):
    def __init__(self, loaded):
        super().__init__(BOOT_RENDER)

    def subscribe(self, app, page, callback):
        new_callback = page.callback is None
        if (new_callback):
            page.callback = callback
            page.app = app
        self.refresh(page)

    def refresh(self, page):
        if not page.callback:
            return
        elif (not page.loading and not page.loaded ):
            self.load_spotify(page)
        else :
            page.loaded = page.my_queue.get()

        page.callback(page.loaded)

    def load_spotify(self, page):
        page.loading = True
        if(not TEST_ENV) :
            thread1 = threading.Thread(target = spotify_manager.refresh_data, args=(page.my_queue,))
        else :
            thread1 = threading.Thread(target = spotify_manager.refresh_devices, args=(page.my_queue,))
        thread1.start()

    def unsubscribe(self):
        super().unsubscribe()

    def set_loaded(loaded):
        self.loaded = loaded


class MenuRendering(Rendering):
    def __init__(self, header = "", lines = [], page_start = 0, total_count = 0):
        super().__init__(MENU_RENDER_TYPE)
        self.lines = lines
        self.header = header
        self.page_start = page_start
        self.total_count = total_count
        self.now_playing = spotify_manager.DATASTORE.now_playing
        self.has_internet = spotify_manager.has_internet

class NowPlayingRendering(Rendering):
    def __init__(self):
        super().__init__(NOW_PLAYING_RENDER)
        self.callback = None
        self.after_id = None
        self.target_volume = SystemController.get_volume()

    def subscribe(self, app, callback):
        if callback == self.callback:
            return
        new_callback = self.callback is None
        self.callback = callback
        self.app = app
        if new_callback:
            self.refresh()

    def refresh(self, volume=None):
        if not self.callback:
            return
        if self.after_id:
            self.app.after_cancel(self.after_id)
        if (volume == None):
            now_playing = spotify_manager.DATASTORE.now_playing
            #volume
            if(SystemController.get_volume() != self.target_volume) :
                SystemController.set_volume(self.target_volume)
        else :
            now_playing = {'name':'', 'artist':'', 'album':'Volume', 'context_name':'', 'is_playing': 'volume', 'progress': self.target_volume, 'duration' : 100, 'track_index': -1}
        now_playing['volume'] = str(self.target_volume)
        self.callback(now_playing)
        self.after_id = self.app.after(500, lambda: self.refresh())

    def unsubscribe(self):
        super().unsubscribe()
        self.callback = None
        self.app = None

class NowPlayingCommand():
    def __init__(self, runnable = lambda:()):
        self.has_run = False
        self.runnable = runnable

    def run(self):
        self.has_run = True
        self.runnable()

class SearchRendering(Rendering):
    def __init__(self, query, active_char):
        super().__init__(SEARCH_RENDER)
        self.query = query
        self.active_char = active_char
        self.loading = False
        self.callback = None
        self.results = None

    def get_active_char(self):
        return ' ' if self.active_char == 26 else chr(self.active_char + ord('a'))

    def subscribe(self, app, callback):
        if (callback == self.callback):
            return
        new_callback = self.callback is None
        self.callback = callback
        self.app = app
        if new_callback:
            self.refresh()

    def refresh(self):
        if not self.callback:
            return
        self.callback(self.query, self.get_active_char(), self.loading, self.results)
        self.results = None

    def unsubscribe(self):
        super().unsubscribe()
        self.callback = None
        self.app = None

class SearchPage():
    def __init__(self, previous_page):
        self.header = "Search"
        self.has_sub_page = True
        self.previous_page = previous_page
        self.live_render = SearchRendering("", 0)
        self.is_title = False

    def nav_prev(self):
        self.live_render.query = self.live_render.query[0:-1]
        self.live_render.refresh()

    def nav_next(self):
        if len(self.live_render.query) > 15:
            return
        active_char = ' ' if self.live_render.active_char == 26 \
          else chr(self.live_render.active_char + ord('a'))
        self.live_render.query += active_char
        self.live_render.refresh()

    def nav_play(self):
        pass

    def nav_up(self):
        self.live_render.active_char += 1
        if (self.live_render.active_char > 26):
            self.live_render.active_char = 0
        self.live_render.refresh()

    def nav_down(self):
        self.live_render.active_char -= 1
        if (self.live_render.active_char < 0):
            self.live_render.active_char = 26
        self.live_render.refresh()

    def run_search(self, query):
        self.live_render.loading = True
        self.live_render.refresh()
        self.live_render.results = spotify_manager.search(query)
        self.live_render.loading = False
        self.live_render.refresh()

    def nav_select(self):
        spotify_manager.run_async(lambda: self.run_search(self.live_render.query))
        return self

    def nav_back(self):
        return self.previous_page

    def render(self):
        return self.live_render

class NowPlayingPage():
    def __init__(self, previous_page, header, command):
        self.has_sub_page = False
        self.previous_page = previous_page
        self.command = command
        self.header = header
        self.live_render = NowPlayingRendering()
        self.is_title = False

    def play_previous(self):
        spotify_manager.play_previous()
        self.live_render.refresh()

    def play_next(self):
        spotify_manager.play_next()
        self.live_render.refresh()

    def toggle_play(self):
        spotify_manager.toggle_play()
        self.live_render.refresh()

    def nav_prev(self):
        spotify_manager.run_async(lambda: self.play_previous())

    def nav_next(self):
        spotify_manager.run_async(lambda: self.play_next())

    def nav_play(self):
        spotify_manager.run_async(lambda: self.toggle_play())

    def nav_up(self):
        vol = self.live_render.target_volume
        if (vol < 100) :
            newVol = vol + 5
            self.live_render.target_volume = newVol
            self.live_render.refresh(True)

    def nav_down(self):
        vol = self.live_render.target_volume
        if (vol > 0) :
            newVol = vol - 5
            self.live_render.target_volume = newVol
            self.live_render.refresh(True)

    def nav_select(self):
        return self

    def nav_back(self):
        return self.previous_page

    def render(self):
        if (not self.command.has_run):
            self.command.run()
        return self.live_render

EMPTY_LINE_ITEM = LineItem()
class MenuPage():
    def __init__(self, header, previous_page, has_sub_page, is_title = False):
        self.index = 0
        self.page_start = 0
        self.header = header
        self.has_sub_page = has_sub_page
        self.previous_page = previous_page
        self.is_title = is_title

    def total_size(self):
        return 0

    def page_at(self, index):
        return None

    def nav_prev(self):
        spotify_manager.run_async(lambda: spotify_manager.play_previous())

    def nav_next(self):
        spotify_manager.run_async(lambda: spotify_manager.play_next())

    def nav_play(self):
        spotify_manager.run_async(lambda: spotify_manager.toggle_play())

    def get_index_jump_up(self):
        return 1

    def get_index_jump_down(self):
        return 1

    def nav_up(self):
        jump = self.get_index_jump_up()
        if(self.index >= self.total_size() - jump):
            return
        if (self.index >= self.page_start + MENU_PAGE_SIZE - jump):
            self.page_start = self.page_start + jump
        self.index = self.index + jump

    def nav_down(self):
        jump = self.get_index_jump_down()
        if(self.index <= (jump - 1)):
            return
        if (self.index <= self.page_start + (jump - 1)):
            self.page_start = self.page_start - jump
            if (self.page_start == 1):
                self.page_start = 0
        self.index = self.index - jump

    def nav_select(self):
        return self.page_at(self.index)

    def nav_back(self):
        return self.previous_page

    def render(self):
        lines = []
        total_size = self.total_size()
        for i in range(self.page_start, self.page_start + MENU_PAGE_SIZE):
            if (i < total_size):
                page = self.page_at(i)
                if (page is None) :
                    lines.append(EMPTY_LINE_ITEM)
                else:
                    line_type = LINE_TITLE if page.is_title else \
                        LINE_HIGHLIGHT if i == self.index else LINE_NORMAL
                    lines.append(LineItem(page.header, line_type, page.has_sub_page))
            else:
                lines.append(EMPTY_LINE_ITEM)
        return MenuRendering(lines=lines, header=self.header, page_start=self.index, total_count=total_size)

class PlaylistsPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__(self.get_title(), previous_page, has_sub_page=True)
        self.playlists = self.get_content()
        self.num_playlists = len(self.playlists)

        self.playlists.sort(key=self.get_idx) # sort playlists to keep order as arranged in Spotify library

    def get_title(self):
        return "Playlists"

    def get_content(self):
        return spotify_manager.DATASTORE.getAllSavedPlaylists()

    def get_idx(self, e): # function to get idx from UserPlaylist for sorting
        if type(e) == spotify_manager.UserPlaylist: # self.playlists also contains albums as it seems and they don't have the idx value
            try:
                return e.idx
            except AttributeError:
                return 0
        else:
            return 0

    def total_size(self):
        return self.num_playlists

    @lru_cache(maxsize=15)
    def page_at(self, index):
        return SinglePlaylistPage(self.playlists[index], self)

class AlbumsPage(PlaylistsPage):
    def __init__(self, previous_page):
        super().__init__(previous_page)

    def get_title(self):
        return "Albums"

    def get_content(self):
        return spotify_manager.DATASTORE.getAllSavedAlbums()

class SearchResultsPage(MenuPage):
    def __init__(self, previous_page, results):
        super().__init__("Search Results", previous_page, has_sub_page=True)
        self.results = results
        tracks, albums, artists = len(results.tracks), len(results.albums), len(results.artists)
        # Add 1 to each count (if > 0) to make room for section header line items
        self.tracks = tracks + 1 if tracks > 0 else 0
        self.artists = artists + 1 if artists > 0 else 0
        self.albums = albums + 1 if albums > 0 else 0
        self.total_count = self.tracks + self.albums + self.artists
        self.index = 1
        # indices of the section header line items
        self.header_indices = [0, self.tracks, self.artists + self.tracks]

    def total_size(self):
        return self.total_count

    def page_at(self, index):
        if self.tracks > 0 and index == 0:
            return PlaceHolderPage("TRACKS", self, has_sub_page=False, is_title=True)
        elif self.artists > 0 and index == self.header_indices[1]:
            return PlaceHolderPage("ARTISTS", self, has_sub_page=False, is_title=True)
        elif self.albums > 0 and index == self.header_indices[2]:
            return PlaceHolderPage("ALBUMS", self, has_sub_page=False, is_title=True)
        elif self.tracks > 0 and  index < self.header_indices[1]:
            track = self.results.tracks[index - 1]
            command = NowPlayingCommand(lambda: spotify_manager.play_track(track.uri))
            return NowPlayingPage(self, track.title, command)
        elif self.albums > 0 and  index < self.header_indices[2]:
            artist = self.results.artists[index - (self.tracks + 1)]
            command = NowPlayingCommand(lambda: spotify_manager.play_artist(artist.uri))
            return NowPlayingPage(self, artist.name, command)
        else:
            album = self.results.albums[index - (self.artists + self.tracks + 1)]
            tracks = self.results.album_track_map[album.uri]
            return InMemoryPlaylistPage(album, tracks, self)

    def get_index_jump_up(self):
        if self.index + 1 in self.header_indices:
            return 2
        return 1

    def get_index_jump_down(self):
        if self.index - 1 in self.header_indices:
            return 2
        return 1

class NewReleasesPage(PlaylistsPage):
    def __init__(self, previous_page):
        super().__init__(previous_page)

    def get_title(self):
        return "New Releases"

    def get_content(self):
        return spotify_manager.DATASTORE.getAllNewReleases()

class ArtistsPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__("Artists", previous_page, has_sub_page=True)

    def total_size(self):
        return spotify_manager.DATASTORE.getArtistCount()

    @lru_cache(maxsize=15)
    def page_at(self, index):
        # play track
        artist = spotify_manager.DATASTORE.getArtist(index)
        command = NowPlayingCommand(lambda: spotify_manager.play_artist(artist.uri))
        return NowPlayingPage(self, artist.name, command)

class SettingsPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__("Settings", previous_page, has_sub_page=True)

        self.pages = [
            AboutPage(self),
            #WifiPage(self),
            AudioPage(self),
            BluetoothPage(self),
        ]
        self.index = 0
        self.page_start = 0

    def nav_select(self):
        self.page_at(self.index).refresh()
        return self.page_at(self.index)

    def get_pages(self):
        return self.pages

    def total_size(self):
        return len(self.get_pages())

    def page_at(self, index):
        return self.get_pages()[index]

class WifiPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__("Wifi", previous_page, has_sub_page=True)
        self.index = 0
        self.page_start = 0


class BluetoothItem(MenuPage):
    def __init__(self, device, previous_page):
        super().__init__(device['name'], previous_page, has_sub_page=False)
        self.device = device

class BluetoothPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__(self.get_title(), previous_page, has_sub_page=True)
        self.devices = self.get_content()
        self.num_devices = len(self.devices)

    def get_title(self):
        return "Bluetooth"

    def get_content(self):
        return Bluetoothctl.get_paired_devices()

    def nav_select(self):
        deviceItem = self.page_at(self.index)
        Bluetoothctl.toggle(deviceItem.device)
        self.devices = self.get_content()
        self.num_devices = len(self.devices)
        return self.previous_page

    def total_size(self):
        return self.num_devices

    def page_at(self, index):
        return BluetoothItem(self.devices[index], self)

    def refresh(self):
        self.devices = self.get_content()
        self.num_devices = len(self.devices)

class AudioPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__(self.get_title(), previous_page, has_sub_page=True)
        self.devices = self.get_content()
        self.num_devices = len(self.devices)

    def get_title(self):
        return "Audio Output"

    def get_content(self):
        return Audioctl.get_audio_output_devices()

    def nav_select(self):
        deviceItem = self.page_at(self.index)
        Audioctl.select(deviceItem.device)
        self.devices = self.get_content()
        self.num_devices = len(self.devices)
        return self.previous_page

    def total_size(self):
        return self.num_devices

    def page_at(self, index):
        return BluetoothItem(self.devices[index], self)

    def refresh(self):
        self.devices = self.get_content()
        self.num_devices = len(self.devices)


class AboutLineItem():
    def __init__(self, title = "", value ="", has_sub_page = False):
        self.header = title
        self.value = value
        self.is_title = False
        self.has_sub_page = has_sub_page
        self.selectable = False

class AboutPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__(self.get_title(), previous_page, has_sub_page=True)
        self.aboutList = self.get_content()
        self.num_list = len(self.aboutList)

    def get_title(self):
        return "About"

    def nav_up(self):
        jump = self.get_index_jump_up()
        if (MENU_PAGE_SIZE >= self.total_size() - self.page_start):
            return
        self.page_start = self.page_start + jump
        self.index = self.page_start + MENU_PAGE_SIZE - 1

    def nav_down(self):
        jump = self.get_index_jump_down()
        if(self.page_start <= (jump - 1)):
            return
        self.page_start = self.page_start - jump
        self.index = self.page_start

    def getserial(self):
        # Extract serial from cpuinfo file
        cpuserial = "DEV000000000"
        try:
            f = open('/proc/cpuinfo','r')
            for line in f:
                if line[0:6]=='Serial':
                    cpuserial = line[10:26]
            f.close()
        except:
            cpuserial = "ERROR000000000"
        return cpuserial

    def getversion(self):
        # Extract serial from cpuinfo file
        version = "ERROR"
        try:
            f = open('/proc/version','r')
            for line in f:
                version = line[14:]
            f.close()
        except:
            version = "ERROR"
        return version

    def getuptime(self):
        t = os.popen('uptime -p').read()[3:-1]
        return t

    def getcapacity(self):
        # Extract serial from cpuinfo file
        capacity = "0"
        try:
            capacity = os.popen(' df -h').read()[:-1]
        except:
            capacity = "ERROR"
        return capacity

    def get_content(self):
        aboutList = []
        aboutList.append(AboutLineItem("Model", "Zero"))
        aboutList.append(AboutLineItem("Capacity", "32 Gib"))
        aboutList.append(AboutLineItem("Version", self.getversion()))
        aboutList.append(AboutLineItem("Serial", self.getserial()))
        aboutList.append(AboutLineItem("Uptime", self.getuptime()))
        return aboutList

    def total_size(self):
        return self.num_list

    def page_at(self, index):
        #command = NowPlayingCommand(lambda: spotify_manager.play_from_playlist(self.playlist.uri, track.uri, None))
        return self.aboutList[index]

    def refresh(self):
        self.aboutList = self.get_content()
        self.num_list = len(self.aboutList)

    def render(self):
        lines = []
        total_size = self.total_size()
        for i in range(self.page_start, self.page_start + MENU_PAGE_SIZE):
            if (i < total_size):
                page = self.page_at(i)
                if (page is None) :
                    lines.append(EMPTY_LINE_ITEM)
                else:
                    line_type = LINE_TITLE if page.is_title else \
                        LINE_HIGHLIGHT if i == self.index else LINE_NORMAL
                    lines.append(LineItem(title = page.header, line_type = line_type, show_arrow = page.has_sub_page, selectable = page.selectable, value = page.value))
            else:
                lines.append(EMPTY_LINE_ITEM)
        return MenuRendering(lines=lines, header=self.header, page_start=self.index, total_count=total_size)

class SinglePlaylistPage(MenuPage):
    def __init__(self, playlist, previous_page):
        # Credit for code to remove emoticons from string: https://stackoverflow.com/a/49986645
        regex_pattern = re.compile(pattern = "["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                            "]+", flags = re.UNICODE)

        super().__init__(regex_pattern.sub(r'',playlist.name), previous_page, has_sub_page=True)
        self.playlist = playlist
        self.tracks = None

    def get_tracks(self):
        if self.tracks is None:
            self.tracks = spotify_manager.DATASTORE.getPlaylistTracks(self.playlist.uri)
        return self.tracks

    def total_size(self):
        return self.playlist.track_count

    def page_at(self, index):
        track = self.get_tracks()[index]
        command = NowPlayingCommand(lambda: spotify_manager.play_from_playlist(self.playlist.uri, track.uri, None))
        return NowPlayingPage(self, track.title, command)

class InMemoryPlaylistPage(SinglePlaylistPage):
    def __init__(self, playlist, tracks, previous_page):
        super().__init__(playlist, previous_page)
        self.tracks = tracks

class SingleTrackPage(MenuPage):
    def __init__(self, track, previous_page, playlist = None, album = None):
        super().__init__(track.title, previous_page, has_sub_page=False)
        self.track = track
        self.playlist = playlist
        self.album = album

    def render(self):
        r = super().render()
        print("render track")
        context_uri = self.playlist.uri if self.playlist else self.album.uri
        spotify_manager.play_from_playlist(context_uri, self.track.uri, None)
        return r

class SavedTracksPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__("Saved Tracks", previous_page, has_sub_page=True)

    def total_size(self):
        return spotify_manager.DATASTORE.getSavedTrackCount()

    def page_at(self, index):
        # play track
        return SingleTrackPage(spotify_manager.DATASTORE.getSavedTrack(index), self)

class PlaceHolderPage(MenuPage):
    def __init__(self, header, previous_page, has_sub_page=True, is_title = False):
        super().__init__(header, previous_page, has_sub_page, is_title)


class BootPage():
    def __init__(self, target_page):
        self.rendering = BootRendering(False)
        self.target_page = target_page
        self.loaded = False
        self.loading = False
        self.my_queue = queue.Queue()
        self.callback = None

    def render(self):
        return BootRendering(False)

class RootPage(MenuPage):
    def __init__(self, previous_page):
        super().__init__("piPod", previous_page, has_sub_page=True)
        self.pages = [
            ArtistsPage(self),
            AlbumsPage(self),
            NewReleasesPage(self),
            PlaylistsPage(self),
            SearchPage(self),
            SettingsPage(self),
            NowPlayingPage(self, "Now Playing", NowPlayingCommand())
        ]
        self.index = 0
        self.page_start = 0

    def get_pages(self):
        if (not spotify_manager.DATASTORE.now_playing):
            return self.pages[0:-1]
        return self.pages

    def total_size(self):
        return len(self.get_pages())

    def page_at(self, index):
        return self.get_pages()[index]
