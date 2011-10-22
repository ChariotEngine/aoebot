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

import config
import re
import sqlite3

def parse_event(self, recv):
    irc_user_nick = recv.split ( '!' ) [ 0 ] . split ( ":")[1]
    irc_user_host = recv.split ( '@' ) [ 1 ] . split ( ' ' ) [ 0 ]
    irc_user_message = self.data_to_message(recv)
    chan = (recv).split()[2]  #channel
    ###logs
    if re.search('^.*01ACTION', irc_user_message) and re.search('01$', irc_user_message):
        irc_user_message_me = irc_user_message.split('01ACTION ')[1][0:-4]
        self.logs(irc_user_nick, chan, 'action', irc_user_message_me, '')
    else:
        self.logs(irc_user_nick, chan, 'privmsg', irc_user_message, '')
    ### logs end
    conn = sqlite3.connect('db/openra.sqlite')   # connect to database
    cur=conn.cursor()
    ### for last message
    sql = """INSERT INTO messages
            (user,message,date_time,channel)
            VALUES
            (
            '"""+irc_user_nick+"""','"""+irc_user_message.replace("'","''")+"""',strftime('%Y-%m-%d-%H-%M-%S'),'"""+chan+"""'
            )
    """
    cur.execute(sql)
    conn.commit()
    ###
    cur.close()

    print ( irc_user_nick + ": " + irc_user_message)
    # Message starts with command prefix?
    if ( irc_user_message != '' ):
        if ( irc_user_message[0] == config.command_prefix ):
            self.command = irc_user_message[1:]
            self.process_command(irc_user_nick, ( chan ))
    ### parse links and bug reports numbers
    self.parse_link(chan, irc_user_message)
    self.parse_bug_num(chan, irc_user_message)
    ###
