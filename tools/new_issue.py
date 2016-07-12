# Copyright 2011-2014 orabot Developers
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

import time
import urllib.request
import json

def start(self):
    if self.irc_host != "irc.freenode.net":
        print("*** [%s] Terminating child process (unsupported): %s" % (self.irc_host, __name__))
        return
    time.sleep(1200)    # wait 20 minutes
    y = bugs_list(self) # request a list from github
    e_bugs = [n['number'] for n in y]
    
    while True:
        time.sleep(1200)    # wait 20 minutes
        e_bugs = detect_bugs(self, e_bugs)

def detect_bugs(self, e_bugs):
    y = bugs_list(self) # request a list from github
    remote_bugs = [n['number'] for n in y]
    
    for i in range(0, 16):
        if remote_bugs[i] not in e_bugs:   # it's a new bug
            report_type = "issue"
            if 'pull_request' in y[i]:
                if y[i]['pull_request']['html_url'] != None:
                    report_type = "pull request"

            pull_or_issues = "pull" if report_type == "pull request" else "issues"
            self.send_message_to_channel(("New %s #%s by %s: %s | https://github.com/angered-ghandi/OpenAOE/%s/%s")
                                        % (report_type,
                                            str(remote_bugs[i]),
                                            y[i]['user']['login'],
                                            y[i]['title'],
                                            pull_or_issues,
                                            str(remote_bugs[i])),
                                        "#openaoe")
            if report_type == "pull request":
                isFirstPR(self, y[i]['user']['login'])

    return remote_bugs

def bugs_list(self):
    url = 'https://api.github.com/repos/angered-ghandi/OpenAOE/issues'
    while True:
        try:
            data = urllib.request.urlopen(url).read().decode()
            return json.loads(data)
        except:
            print("*** [%s] Could not fetch a list of OpenAOE bugs, apparently 'Exceed Rate Limit'" % self.irc_host)
            time.sleep(7200)    # wait 2 hours

def isFirstPR(self, reportedBy):
    url = 'https://api.github.com/search/issues?q=repo:angered-ghandi/OpenAOE+type:pr+author:%s' % reportedBy
    try:
        data = urllib.request.urlopen(url).read().decode()
        e = json.loads(data)
        if e['total_count'] == 1:
            self.send_message_to_channel( "Thanks for making your first Pull Request, %s!" % reportedBy, "#openaoe")
    except Exception as e:
        print(e)
