# Copyright 2011 orabot Developers
#
# This file is part of orabot, which is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import socket, multiprocessing, time
import os
import re
from datetime import date
import sqlite3
import urllib.request
import imp
import inspect
import signal
import html.parser

import db_process
import notifications
import config
import spam_filter
### commands are in 'commands' directory
from commands import *
### irc events in 'irc' directory
from irc import *
### notifications package
from notifications import openra_topic
from notifications import openra_bugs
from notifications import github_commits
from notifications import openra_game

###
if not os.path.exists('db/openra.sqlite'):
    db_process.start()
###

# Defining a class to run the server. One per connection. This class will do most of our work.
class IRC_Server:

    # The default constructor - declaring our global variables
    # This needs to support an alternate nick.
    def __init__(self, host, port, nick, channel , password =""):
        self.irc_host = host
        self.irc_port = port
        self.irc_nick = nick
        self.irc_channel = channel
        self.irc_sock = socket.socket ( socket.AF_INET, socket.SOCK_STREAM )
        self.is_connected = False
        self.should_reconnect = False
        self.command = ""
        self.quit_store = []
        self.join_store = []

    ## The destructor - Close socket.
    def __del__(self):
        self.irc_sock.close()

    def ircbot(self):
        if ( config.notifications == True ):
            # run notifications
            print("Notifications support...                        OK")
            self.notifications()
        self.connect()

    def notifications(self):
        ora_topic = multiprocessing.Process(target=openra_topic.start, args=(self,))
        ora_bugs = multiprocessing.Process(target=openra_bugs.start, args=(self,))
        git_commits = multiprocessing.Process(target=github_commits.start, args=(self,))
        ora_game = multiprocessing.Process(target=openra_game.start, args=(self,))
        
        ora_topic.start()
        ora_bugs.start()
        git_commits.start()
        ora_game.start()

    # This is the bit that controls connection to a server & channel.
    def connect(self):
        self.should_reconnect = True
        try:
            self.irc_sock.connect ((self.irc_host, self.irc_port))
        except:
            print ("Error: Could not connect to IRC; Host: " + str(self.irc_host) + "Port: " + str(self.irc_port))
            exit(1) # We should make it recconect if it gets an error here
        print ("Connected to: " + str(self.irc_host) + ":" + str(self.irc_port))

        str_buff = ("NICK %s \r\n") % (self.irc_nick)
        self.irc_sock.send (str_buff.encode())
        print ("Setting bot nick to " + str(self.irc_nick) )
        time.sleep(2)
        recv = self.irc_sock.recv( 4096 )
        recv=self.decode_stream(recv)
        if str(recv).find ( " 433 * "+self.irc_nick+" " ) != -1:
            print('Nick is already in use!!! Change nickname and restart bot!')
            return

        str_buff = ("USER %s 8 * :X\r\n") % (self.irc_nick)
        self.irc_sock.send (str_buff.encode())
        print ("Setting User")
        # Insert Alternate nick code here.

        if config.nickserv == True:
            print ("Attempting to identify with NickServ...")
            data = "identify "+config.nickserv_password
            self.irc_sock.send( (("PRIVMSG %s :%s\r\n") % ('NickServ', data)).encode() )

        for i in range(len(self.irc_channel)):
            str_buff = ( "JOIN %s \r\n" ) % (self.irc_channel[i])
            self.irc_sock.send (str_buff.encode())
            print ("Joining channel " + self.irc_channel[i] )

        start_up_db = multiprocessing.Process(target=self.startup_db_check)
        try:
            pass
            #start_up_db.start()
        except KeyboardInterrupt:
            start_up_db.terminate()

        self.is_connected = True
        self.listen()

    def listen(self):
        while self.is_connected:
            recv = self.irc_sock.recv( 4096 )
            recv=self.decode_stream(recv)

            data = self.handle_recv(str(recv))
            for recv in data:
                if recv.find ( "PING" ) != -1:
                    self.irc_sock.send ( ("PONG "+ recv.split() [ 1 ] + "\r\n").encode() )

                if recv.find ( " PRIVMSG " ) != -1:
                    imp.reload(privmsg_e)
                    privmsg_event = multiprocessing.Process(target=privmsg_e.parse_event, args=(self,recv,))
                    try:
                        privmsg_event.start()
                    except KeyboardInterrupt:
                        privmsg_event.terminate()

                if recv.find ( " JOIN " ) != -1:
                    imp.reload(join_e)
                    join_e.parse_event(self, recv)

                if recv.find ( " QUIT " ) != -1:
                    imp.reload(quit_e)
                    quit_e.parse_event(self, recv)

                if recv.find ( " PART " ) != -1:
                    imp.reload(part_e)
                    part_e.parse_event(self, recv)

                if recv.find ( " NICK " ) != -1:
                    imp.reload(nick_e)
                    nick_e.parse_event(self, recv)

                if recv.find ( " TOPIC " ) != -1:
                    imp.reload(topic_e)
                    topic_e.parse_event(self, recv)

                if recv.find ( " KICK " ) != -1:
                    imp.reload(kick_e)
                    kick_e.parse_event(self, recv)

        if self.should_reconnect:
            self.connect()

    def data_to_message(self, data):
        data = data[data.find(" :")+2:]
        return data

    #handle as single line request as multiple ( split recv into pieces before processing it )
    def handle_recv(self, recv):
        regex = re.compile('(.*?)\r\n')
        recv = regex.findall(recv)
        return recv

    # helper to remove some insanity.
    def send_reply(self, data, user, channel):
        target = channel if channel.startswith('#') else user
        self.send_message_to_channel(data,target)

    #another helper
    def decode_stream(self, stream):
        try:
            return stream.decode("utf8")
        except:
            return stream.decode("CP1252")

    # This function sends a message to a channel or user
    def send_message_to_channel(self, data, channel):
        print ( ( "%s: %s") % (self.irc_nick, data[:256]) )
        self.irc_sock.send( (("PRIVMSG %s :%s\r\n") % (channel, data[:256])).encode() )
        ### logs
        self.logs(self.irc_nick, channel, 'privmsg', str(data), '')

    def send_notice(self, data, user):
        print ( ( "NOTICE to %s: %s" ) % (user, data) )
        str_buff = ( "NOTICE %s :%s\r\n" ) % (user,data)
        self.irc_sock.send (str_buff.encode())

    def startup_db_check(self):
        ### change existing users status to offline if their status in DB is online but they are not on any of the channels and upside down
        conn = sqlite3.connect('../db/openra.sqlite')
        cur = conn.cursor()
        sql = """SELECT user,state,channels FROM users
        """
        cur.execute(sql)
        records = cur.fetchall()
        conn.commit()
        time.sleep(3)
        if ( len(records) != 0 ):
            user_nicks = self.parse_names(self.get_names(config.channels.split(',')[0]))
            db_usernames = []
            for i in range(len(records)):
                db_usernames.append(records[i][0])
            for chan in config.channels.split(','):
                time.sleep(2)
                user_nicks = self.parse_names(self.get_names(chan))
                if ( len(user_nicks) != 0 ):    #no error on NAMES
                    for i in range(len(records)):
                        if ( records[i][0] not in user_nicks ):
                            if ( str(records[i][1]) == '1' ):
                                if ( records[i][0] not in self.join_store ):
                                    sql = """UPDATE users
                                            SET state = 0, channels = ''
                                            WHERE user = '"""+records[i][0]+"""'
                                    """
                                    cur.execute(sql)
                                    conn.commit()
                                else:
                                    print("DEBUG: DB CHECK!!!, but user managed to join during that check")
                        else:
                            if ( str(records[i][1]) == '0' ):
                                if ( records[i][0] not in self.quit_store ):
                                    sql = """UPDATE users
                                            SET state = 1, channels = '"""+chan+"""'
                                            WHERE user = '"""+records[i][0]+"""'
                                    """
                                    cur.execute(sql)
                                    conn.commit()
                                else:
                                    print("DEBUG: DB CHECK!!!, but user managed to leave during that check")
                            else:
                                if ( chan not in records[i][2].split(',') ):
                                    if ( records[i][2] == '' ) or ( records[i][2] == None ):
                                        channel_to_db = chan
                                    else:
                                        channel_to_db = records[i][2]+','+chan
                                    sql = """UPDATE users
                                            SET channels = '"""+channel_to_db+"""'
                                            WHERE user = '"""+records[i][0]+"""'
                                    """
                                    cur.execute(sql)
                                    conn.commit()
                for username in user_nicks:
                    if ( username not in db_usernames ):
                        if ( username not in self.join_store ):
                            sql = """INSERT INTO users
                                    (user,state,channels)
                                    VALUES
                                    (
                                    '"""+username+"""',1,'"""+chan+"""'
                                    )
                            """
                            cur.execute(sql)
                            conn.commit()
                print("DB iterations finished")
        cur.close()

    def get_names(self, channel):
        str_buff = ( "NAMES %s \r\n" ) % (channel)
        self.irc_sock.send (str_buff.encode())
        #recover all nicks on channel
        recv = self.irc_sock.recv( 1024 )
        recv = self.decode_stream( recv )
        return recv

    def parse_names(self, recv):
        user_nicks = []
        if recv.find ( " 353 "+config.bot_nick ) != -1:
            user_nicks = recv.split(':')[2].rstrip()
            user_nicks = user_nicks.replace('+','').replace('@','').replace('%','')
            user_nicks = user_nicks.split(' ')
        return user_nicks

    def parse_html(self, string):
        h = html.parser.HTMLParser()
        string = h.unescape(string)
        return string.strip()

    # This function takes a channel, which must start with a #.
    def join_channel(self, channel):
        if (channel[0] == "#"):
            str_buff = ( "JOIN %s \r\n" ) % (channel)
            self.irc_sock.send (str_buff.encode())
            # This needs to test if the channel is full

    # This function takes a channel, which must start with a #.
    def quit_channel(self, channel):
        if (channel[0] == "#"):
            str_buff = ( "PART %s \r\n" ) % (channel)
            self.irc_sock.send ( str_buff.encode() )
            # This needs to modify the list of active channels
    def topic(self, channel, topic):
        str_buff = ("TOPIC %s :%s\r\n") % (channel, topic)
        self.irc_sock.send ( str_buff.encode() )

        channel_names = self.get_names(channel)
        if channel_names.find ( " 353 "+config.bot_nick ) != -1:
            user_nicks = channel_names.split(':')[2].rstrip()
            user_nicks = user_nicks.split(' ')
            if ( '@' + config.bot_nick not in user_nicks ):
                self.send_message_to_channel( ("I tried to change the topic of this channel but do not have rights for it"), channel)

    def logs(self, irc_user, channel, logs_of, some_data, some_more_data):
        if config.write_logs == True:
            chan_d = str(channel).replace('#','')
            t = time.localtime( time.time() )
            time_prefix = time.strftime( '%Y-%m-%dT%T', t )
            filename = config.log_dir + chan_d + time.strftime( '/%Y/%m/%d', t )
            if channel in config.log_channels.split(','):
                if ( logs_of == 'privmsg' ):
                    row = ' <'+irc_user+'> '+some_data+'\n'
                elif ( logs_of == 'action' ):
                    row = ' * '+irc_user+' '+some_data+'\n'
                elif ( logs_of == 'join' ):
                    row = ' *** '+irc_user+' <'+some_data+'> has joined '+channel+'\n'
                elif ( logs_of == 'quit' ):
                    row = ' *** '+irc_user+' <'+some_data+'> has quit IRC\n'
                elif ( logs_of == 'part' ):
                    row = ' *** '+irc_user+' <'+some_data+'> has left '+channel+'\n'
                elif ( logs_of == 'nick' ):
                    row = ' *** '+irc_user+' is now known as '+some_data+'\n'
                elif ( logs_of == 'topic' ):
                    row = ' *** '+irc_user+' changes topic to "'+some_data+'"\n'
                elif ( logs_of == 'kick' ):
                    row = ' *** '+irc_user+' was kicked by '+some_data+' ('+some_more_data+')\n'
                else:
                    return  # probably an error.
                dir = os.path.dirname(filename)
                try:
                    if not os.path.exists(dir):
                        os.makedirs(dir)
                    file = open(filename,'a')
                    file.write(time_prefix + row)
                    file.close()
                except:
                    print('####### ERROR !!! ###### Probably no write permissions to logs directory!')

    def data_from_url(self, url, bytes):
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-agent', 'Mozilla/5.0')]
        data = opener.open(url).read(bytes)
        try:
            encoding = str(data).lower().split('charset=')[1].split('"')[0]
            data = data.decode(encoding)
        except: #no encoding found
            data = data.decode('utf-8')
        return data

    def title_from_url(self, url):
        # todo: security: can force the bot to output anything we like into
        #                 the channel.
        data = self.data_from_url(url, 8192)
        rx_title = re.compile(r'<title>(.*?)</title>', re.IGNORECASE)
        titles = rx_title.findall(data.replace('\n',' '))
        if ( titles != [] ):
            title = self.parse_html(titles[0])
            return title
        else:
            raise Exception("Exception: " + url + " does not contain title")

    def parse_link(self, channel, message):
        if re.search('.*http.*://.*', message):
            flood_protection = 0
            matches = re.findall(r"http.?://[^\s]*", message)
            for http_link in matches:
                flood_protection = flood_protection + 1
                if flood_protection == 5:
                    time.sleep(6)
                    flood_protection = 0
                link = http_link.split('://')[1]
                pre = http_link.split('http')[1].split('//')[0]
                link = 'http'+pre+'//'+link
                if re.search("^#", channel):
                    if re.search('http.*youtube.com/watch.*', link):
                        link = link.split('&')[0]
                        try:
                            title = self.title_from_url(link).split('- YouTube')[0]
                            if ( title != 'YouTube - Broadcast Yourself.' ):    #video exists
                                self.send_message_to_channel( ("Youtube: " + title), channel )
                        except Exception as e:
                            print(e)    #probably socket error or http 404 error in title_from_url() or title not found
                    else:
                        try:
                            title = self.title_from_url(link)
                            self.send_message_to_channel( ("Title: " + title), channel )
                        except Exception as e:
                            print(e)    #probably socket error or http 404 error in title_from_url() or title not found
            flood_protection = 0

    def parse_bug_num(self, channel, message):
        matches = re.findall("#([0-9]*)", message)
        if ( matches != [] ):
            flood_protection = 0    
            if re.search("^#", channel):
                for bug_report in matches:
                    if ( bug_report == '' ):
                        return
                    flood_protection = flood_protection + 1
                    if flood_protection == 5:
                        time.sleep(6)
                        flood_protection = 0
                    url = 'http://bugs.open-ra.org/issues/'+bug_report
                    try:
                        fetched = self.title_from_url(url).split('OpenRA - ')[1].split(' - open-ra')[0]
                        self.send_message_to_channel( (fetched+" | "+url), channel )
                    except Exception as e:
                        print(e)
                flood_protection = 0

    # This function is for pickup matches code
    def players_for_mode(self, mode):
        return sum( map( int, mode.split('v') ) )

    # Special admin commands for Op/HalfOp/Voice
    def OpVoice(self, user, channel):
        recv = self.get_names(channel)
        if recv.find ( " 353 "+config.bot_nick ) != -1:
            user_nicks = recv.split(':')[2].rstrip()
            if '+'+user in user_nicks.split() or '@'+user in user_nicks.split() or '%'+user in user_nicks.split():
                return True
            else:
                self.send_reply( ("No rights!"), user, channel )
                return False

    # Execute command
    def evalCommand(self, commandname, user, channel):
        try:
            imp.find_module('commands/'+commandname)
        except:
            return  #no such command
        imp.reload(eval(commandname))
        command_function = getattr(eval(commandname), commandname, None)
        if command_function != None:
            if inspect.isfunction(command_function):
                
                class TimedOut(Exception): # Raised if timed out.
                    pass

                def signal_handler(signum, frame):
                    raise TimedOut("Timed out!")

                signal.signal(signal.SIGALRM, signal_handler)

                signal.alarm(config.command_timeout)    #Limit command execution time
                try:
                    command_function(self, user, channel)
                    signal.alarm(0)
                except TimedOut as msg:
                    self.send_reply( ("Timed out!"), user, channel)

    def process_command(self, user, channel):
        command = (self.command)
        # Break the command into pieces, so we can interpret it with arguments
        command = command.split()

############    COMMADS:
        ### All public commands go here
        # The command isn't case sensitive
        if spam_filter.start(self, user, channel):
            # This line makes sure an actual command was sent, not a plain command prefix
            if ( len(command) == 0):
                error = "Usage: "+config.command_prefix+"command [arguments]"
                self.send_reply( (error), user, channel )
                return
            self.evalCommand(command[0].lower(), user, channel)
#####
class BotCrashed(Exception): # Raised if the bot has crashed.
    pass

def main():
    # Here begins the main programs flow:
    connect_class = IRC_Server(config.server, config.port, config.bot_nick, config.channels.split(','))
    run_connect_class = multiprocessing.Process(None,connect_class.ircbot,name="IRC Server" )
    run_connect_class.start()
    try:
        while(connect_class.should_reconnect):
            time.sleep(5)
        run_connect_class.join()
    except KeyboardInterrupt: # Ctrl + C pressed
        pass # We're ignoring that Exception, so the user does not see that this Exception was raised.
    if run_connect_class.is_alive:
        run_connect_class.terminate()
        run_connect_class.join() # Wait for terminate
    if run_connect_class.exitcode == 0 or run_connect_class.exitcode < 0:
        print("Bot exited.")
    else:
        raise BotCrashed("The bot has crashed")
