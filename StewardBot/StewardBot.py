#!/usr/bin/env python
# -*- coding: utf-8 -*-
from sseclient import SSEClient as EventSource
from irc.bot import SingleServerIRCBot
from irc.client import NickMask
from datetime import datetime
from jaraco.stream import buffer
from irc.client import ServerConnection
import irc.client
import pymysql
import os
import re
import sys
import threading
import time
import json
from configparser import ConfigParser

import config

# DB data
dbconfig = ConfigParser()
dbconfig.read_string(open(os.path.expanduser('~/.my.cnf'), 'r').read())
SQLuser = dbconfig['client']['user']
SQLpassword = dbconfig['client']['password']
SQLhost = dbconfig['client']['host']
SQLdb = config.dbname

# common queries
queries = {
    "privcloaks": "(select p_cloak from privileged) union (select s_cloak from stewards)",
    "ignoredusers": "(select i_username from ignored) union (select s_username from stewards)",
    "stalkedpages": "select f_page from followed",
    "listenedchannels": "select l_channel from listen",
    "stewardusers": "select s_username from stewards",
    "stewardnicks": "select s_nick from stewards",
    "stewardoptin": "select s_nick from stewards where s_optin=1",
}


def nm_to_n(nm):
    """Convert nick mask from source to nick."""
    return NickMask(nm).nick


def query(sqlquery, one=True):
    db = pymysql.connect(
        db=SQLdb,
        host=SQLhost,
        user=SQLuser,
        passwd=SQLpassword)
    cursor = db.cursor()
    cursor.execute(sqlquery)
    db.close()
    res = list(cursor.fetchall())
    res.sort(key=lambda x: x if isinstance(x, str) else "")
    if one:
        return [i[0] for i in res if i]
    else:
        return res


def modquery(sqlquery):
    db = pymysql.connect(
        db=SQLdb,
        host=SQLhost,
        user=SQLuser,
        passwd=SQLpassword)
    cursor = db.cursor()
    cursor.execute(sqlquery)
    db.commit()
    db.close()


class FreenodeBot(SingleServerIRCBot):

    def __init__(self):
        self.server = config.server
        self.channel = config.channel
        self.nickname = config.nick
        self.password = config.password
        self.owner = config.owner
        self.privileged = query(queries["privcloaks"])
        self.listened = query(queries["listenedchannels"])
        self.optin = query(queries["stewardoptin"])
        self.steward = query(queries["stewardnicks"])
        self.quiet = False
        self.notify = True
        self.randmess = config.randmess
        self.listen = True
        self.badsyntax = "Unrecognized command. Type @help for more info."
        SingleServerIRCBot.__init__(
            self, [(self.server, 6667)], self.nickname, self.nickname)

    def on_error(self, c, e):
        print(e.target)
        self.die()

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")
        time.sleep(1)  # latency problem?
        c.privmsg("NickServ", 'GHOST ' + self.nickname + ' ' + self.password)
        c.nick(self.nickname)
        time.sleep(1)  # latency problem?
        c.privmsg("NickServ", 'IDENTIFY ' + self.password)

    def on_welcome(self, c, e):
        c.privmsg("NickServ", 'GHOST ' + self.nickname + ' ' + self.password)
        c.privmsg("NickServ", 'IDENTIFY ' + self.password)
        time.sleep(10)  # let identification succeed before joining channels
        c.join(self.channel)
        if self.listen and self.listened:
            for chan in self.listened:
                c.join(chan)

    def on_ctcp(self, c, event):
        if event.arguments[0] == "VERSION":
            c.ctcp_reply(
                nm_to_n(
                    event.source),
                "Bot for informing Wikimedia stewards on " +
                self.channel)
        elif event.arguments[0] == "PING":
            if len(event.arguments) > 1:
                c.ctcp_reply(nm_to_n(event.source), "PING " + event.arguments[1])

    def on_action(self, c, event):
        who = "<" + self.channel + "/" + nm_to_n(event.source) + "> "
        print("[" + time.strftime("%d.%m.%Y %H:%M:%S") + "] * " + who + event.arguments[0])

    def on_privmsg(self, c, e):
        nick = nm_to_n(e.source)
        a = e.arguments[0]
        nocando = "This command cannot be used via query!"
        print("[" + time.strftime("%d.%m.%Y %H:%M:%S") + "] <private/" + nick + "> " + a)
        if a[0] == "@" or a.lower().startswith(self.nickname.lower() + ":"):
            if a[0] == "@":
                command = a[1:]
            else:
                command = re.sub(
                    "(?i)%s:" %
                    self.nickname.lower(),
                    "",
                    a).strip(" ")
            if command.lower() == "die":
                if self.getcloak(e.source) == self.owner:
                    self.do_command(e.source, command)
                else:
                    self.msg(nocando, nick)
            # Start of Anti-PiR hack
            # elif self.startswitharray(command.lower(), ["help", "privileged list", "ignored list", "stalked list", "listen list", "stew users", "stew nicks", "stew optin", "stew info"]):
            #    self.do_command(e, string.strip(command), nick)
            # elif command.lower().startswith("huggle"):
            #    self.msg(nocando, nick)
            # End of Anti-PiR hack
            elif self.getcloak(e.source).lower() in self.privileged:
                self.do_command(e.source, command.strip(), nick)
            else:
                self.msg(self.badsyntax, nick)
        elif a.lower().startswith("!steward"):
            # self.attention(nick)
            self.msg(nocando, nick)
        elif self.getcloak(e.source).lower() == self.owner:
            if a[0] == "!":
                self.connection.action(self.channel, a[1:])
            else:
                self.msg(a)

    def on_pubmsg(self, c, event):
        timestamp = "[" + time.strftime("%d.%m.%Y %H:%M:%S",
                                        time.localtime(time.time())) + "] "
        nick = event.source.nick
        a = event.arguments[0]
        where = event.target
        who = "<" + where + "/" + nick + "> "
        if where == self.channel:
            print(timestamp + who + a)
            if a[0] == "@" or a.lower().startswith(
                    self.nickname.lower() + ":"):
                # Start of Anti-PiR hack
                evilchars = (";", "'", '"')
                for evilchar in evilchars:
                    if evilchar in a:
                        self.msg(
                            "Your command contains prohibited characters. Please repeat the command without them.",
                            self.channel)
                        return
                # End of Anti-PiR hack

                if a[0] == "@":
                    command = a[1:]
                else:
                    command = re.sub("(?i)%s:" %
                                     self.nickname.lower(), "", a).strip(" ")
                if command.lower() in ["die"] or self.startswitharray(
                    command.lower(),
                    [
                        "steward",
                        "huggle",
                        "help",
                        "privileged list",
                        "ignored list",
                        "stalked list",
                        "listen list",
                        "stew users",
                        "stew nicks",
                        "stew optin",
                        "stew info"]):
                    self.do_command(event.source, command.strip())
                elif self.getcloak(event.source) and self.getcloak(event.source).lower() in self.privileged:
                    self.do_command(event.source, command.strip())
                else:
                    # if not self.quiet: self.msg("You're not allowed to issue commands.")
                    pass
        if a.lower().startswith("!steward"):
            if where != self.channel:
                print(timestamp + who + a)
            reason = re.sub("(?i)!steward", "", a).strip(" ")
            self.attention(nick, where, reason)

    def do_command(self, e, cmd, target=None):
        nick = nm_to_n(e)
        if not target:
            target = self.channel
        c = self.connection

        # On/Off
        if cmd.lower() == "quiet":
            if not self.quiet:
                self.msg("I'll be quiet :(", target)
                self.quiet = True
        elif cmd.lower() == "speak":
            if self.quiet:
                self.msg("Back in action :)", target)
                self.quiet = False
        elif cmd.lower() == "mlock":
            if not self.quiet:
                self.msg("You have 10 seconds!", target)
                self.quiet = True
                time.sleep(10)
                self.quiet = False
        elif cmd.lower() == "notify on":
            if not self.notify:
                self.msg("Notification on", target)
                self.notify = True
        elif cmd.lower() == "notify off":
            if self.notify:
                self.msg("Notification off", target)
                self.notify = False
        elif cmd.lower() == "randmsg on":
            if not self.randmess:
                self.msg("Message notification on", target)
                self.randmess = True
        elif cmd.lower() == "randmsg off":
            if self.randmess:
                self.msg("Message notification off", target)
                self.randmess = False

        # Notifications
        elif cmd.lower().startswith("steward"):
            self.msg("Stewards: Attention requested by %s ( %s )" %
                     (nick, " ".join(self.optin)))

        # Privileged
        elif cmd.lower().startswith("privileged"):
            self.do_privileged(
                re.sub(
                    "(?i)^privileged",
                    "",
                    cmd).strip(" "),
                target,
                nick)

        # Ignored
        elif cmd.lower().startswith("ignored"):
            self.do_ignored(
                re.sub(
                    "(?i)^ignored",
                    "",
                    cmd).strip(" "),
                target,
                nick)

        # Stalked
        elif cmd.lower().startswith("stalked"):
            self.do_stalked(
                re.sub(
                    "(?i)^stalked",
                    "",
                    cmd).strip(" "),
                target,
                nick)

        # Listen
        elif cmd.lower().startswith("listen"):
            self.do_listen(
                re.sub(
                    "(?i)^listen",
                    "",
                    cmd).strip(" "),
                target,
                nick)

        # Stewards
        elif cmd.lower().startswith("stew"):
            self.do_steward(
                re.sub(
                    "(?i)^stew",
                    "",
                    cmd).strip(" "),
                target,
                nick)

        # Help
        elif cmd.lower() == "help":
            self.msg(
                "Help = https://stewardbots.toolforge.org/StewardBot/StewardBot.html",
                nick)

        # Test
        elif cmd.lower() == "test":
            self.msg('The bot seems to see your message')

        # Huggle
        elif cmd.lower().startswith("huggle"):
            who = cmd[6:].strip(" ")
            self.connection.action(self.channel, "huggles " + who)

        # Die
        elif cmd.lower() == "die":
            if self.getcloak(e) != self.owner:
                if not self.quiet:
                    self.msg("You can't kill me; you're not my owner! :P")
            else:
                self.msg("Goodbye!")
                c.part(self.channel, ":Process terminated.")
                bot2.connection.part(bot2.channel)
                if self.listen and self.listened:
                    for chan in self.listened:
                        self.connection.part(chan, ":Process terminated.")
                bot2.connection.quit()
                bot2.disconnect()
                c.quit()
                self.disconnect()
                os._exit(os.EX_OK)

        # Other
        elif not self.quiet:
            pass  # self.msg(self.badsyntax, target)

    def attention(self, nick, channel=None, reason=None):
        if self.notify:
            if not channel or channel == self.channel:
                self.msg("Stewards: Attention requested by %s ( %s )" %
                         (nick, " ".join(self.steward)))
            else:
                self.msg("Stewards: Attention requested ( %s )" %
                         (" ".join(self.steward)))
                messg = "Attention requested by %s on %s" % (nick, channel)
                if reason:
                    messg += " with the following reason: " + reason
                self.msg(messg)

    def do_privileged(self, cmd, target, nick):
        if cmd.lower().startswith("list"):
            who = re.sub("(?i)^list", "", cmd).strip(" ")
            who = who.split(" ")[0]
            if who in ["all", "*"]:
                privnicks = query(
                    "(select p_nick from privileged) union (select s_nick from stewards)")
                self.msg(
                    "privileged nicks (including stewards): " +
                    ", ".join(privnicks),
                    nick)
            else:
                privnicks = query("select p_nick from privileged")
                self.msg("privileged nicks: " + ", ".join(privnicks), nick)
        elif cmd.lower().startswith("get"):
            who = re.sub("(?i)^get", "", cmd).strip(" ")
            who = who.split(" ")[0]
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a nick", target)
            else:
                privcloak = query(
                    'select p_cloak from privileged where p_nick="%s"' %
                    who)
                if len(privcloak) == 0:
                    self.msg(
                        "%s is not in the list of privileged users!" %
                        who, target)
                else:
                    self.msg(
                        "The cloak of privileged user %s is %s" %
                        (who, privcloak[0]), target)
        elif cmd.lower().startswith("add"):
            who = re.sub("(?i)^add", "", cmd).strip(" ")
            wholist = who.split(" ")
            if len(wholist) < 2:
                if not self.quiet:
                    self.msg("You have to specify a nick and a cloak", target)
            else:
                pnick = wholist[0]
                pcloak = wholist[1].lower()
                if len(
                    query(
                        'select p_nick from privileged where p_nick="%s"' %
                        pnick)) > 0:
                    if not self.quiet:
                        self.msg("%s is already privileged!" % pnick, target)
                else:
                    modquery(
                        'insert into privileged values (0, "%s", "%s")' %
                        (pnick, pcloak))
                    # update the list of privileged cloaks
                    self.privileged = query(queries["privcloaks"])
                    if not self.quiet:
                        self.msg(
                            "%s added to the list of privileged users!" %
                            pnick, target)
        elif self.startswitharray(cmd.lower(), ["remove", "delete"]):
            who = re.sub("(?i)^(remove|delete)", "", cmd).strip(" ")
            who = who.split(" ")[0]
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a nick", target)
            else:
                if len(
                    query(
                        'select p_nick from privileged where p_nick="%s"' %
                        who)) == 0:
                    if not self.quiet:
                        self.msg(
                            "%s is not in the list of privileged users!" %
                            who, target)
                else:
                    modquery('delete from privileged where p_nick="%s"' % who)
                    # update the list of privileged cloaks
                    self.privileged = query(queries["privcloaks"])
                    if not self.quiet:
                        self.msg(
                            "%s removed from the list of privileged users!" %
                            who, target)
        elif self.startswitharray(cmd.lower(), ["change", "edit", "modify", "rename"]):
            who = re.sub(
                "(?i)^(change|edit|modify|rename)",
                "",
                cmd).strip(" ")
            wholist = who.split(" ")
            if len(wholist) < 2:
                if not self.quiet:
                    self.msg(
                        "You have to specify a nick and a cloak or another nick", target)
            else:
                pnick = wholist[0]
                pcloak = wholist[1]
                renamecloak = False
                if "/" in pcloak:
                    pcloak = pcloak.lower()
                    renamecloak = True
                if len(
                    query(
                        'select p_nick from privileged where p_nick="%s"' %
                        pnick)) == 0:
                    if not self.quiet:
                        self.msg(
                            "%s is not in the list of privileged users!" %
                            pnick, target)
                else:
                    if renamecloak:
                        modquery(
                            'update privileged set p_cloak = "%s" where p_nick = "%s"' %
                            (pcloak, pnick))
                        # update the list of privileged cloaks
                        self.privileged = query(queries["privcloaks"])
                        if not self.quiet:
                            self.msg(
                                "Changed the cloak for %s in the list of privileged users!" %
                                pnick, target)
                    else:
                        modquery(
                            'update privileged set p_nick = "%s" where p_nick = "%s"' %
                            (pcloak, pnick))
                        if not self.quiet:
                            self.msg(
                                "Changed the privileged user from %s to %s!" %
                                (pnick, pcloak), target)
        else:
            if not self.quiet:
                self.msg(self.badsyntax, target)

    def do_ignored(self, cmd, target, nick):
        if cmd.lower().startswith("list"):
            who = re.sub("(?i)^list", "", cmd).strip(" ")
            who = who.split(" ")[0]
            if who in ["all", "*"]:
                ignoredusers = query(queries["ignoredusers"])
                self.msg(
                    "ignored users (including stewards): " +
                    ", ".join(ignoredusers),
                    nick)
            else:
                ignoredusers = query("select i_username from ignored")
                self.msg("ignored users: " + ", ".join(ignoredusers), nick)
        elif cmd.lower().startswith("add"):
            who = re.sub("(?i)^add", "", cmd).strip(" ")
            who = who.split(" ")[0]
            who = who.replace("_", " ")
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a username", target)
            else:
                who = who[0].upper() + who[1:]
                if len(
                    query(
                        'select i_username from ignored where i_username="%s"' %
                        who)) > 0:
                    if not self.quiet:
                        self.msg("%s is already ignored!" % who, target)
                else:
                    modquery('insert into ignored values (0, "%s")' % who)
                    # update the list of ignored users
                    bot2.ignored = query(queries["ignoredusers"])
                    if not self.quiet:
                        self.msg(
                            "%s added to the list of ignored users!" %
                            who, target)
        elif self.startswitharray(cmd.lower(), ["remove", "delete"]):
            who = re.sub("(?i)^(remove|delete)", "", cmd).strip(" ")
            who = who.split(" ")[0]
            who = who.replace("_", " ")
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a username", target)
            else:
                who = who[0].upper() + who[1:]
                if len(
                    query(
                        'select i_username from ignored where i_username="%s"' %
                        who)) == 0:
                    if not self.quiet:
                        self.msg(
                            "%s is not in the list of ignored users!" %
                            who, target)
                else:
                    modquery('delete from ignored where i_username="%s"' % who)
                    # update the list of ignored users
                    bot2.ignored = query(queries["ignoredusers"])
                    if not self.quiet:
                        self.msg(
                            "%s removed from the list of ignored users!" %
                            who, target)
        elif self.startswitharray(cmd.lower(), ["change", "edit", "modify", "rename"]):
            who = re.sub(
                "(?i)^(change|edit|modify|rename)",
                "",
                cmd).strip(" ")
            wholist = who.split(" ")
            if len(wholist) < 2:
                if not self.quiet:
                    self.msg("You have to specify two usernames", target)
            else:
                iuser1 = wholist[0]
                iuser2 = wholist[1]
                iuser1 = iuser1[0].upper() + iuser1[1:]
                iuser2 = iuser2[0].upper() + iuser2[1:]
                iuser1 = iuser1.replace("_", " ")
                iuser2 = iuser2.replace("_", " ")
                if len(
                    query(
                        'select i_username from ignored where i_username="%s"' %
                        iuser1)) == 0:
                    if not self.quiet:
                        self.msg(
                            "%s is not in the list of ignored users!" %
                            iuser1, target)
                else:
                    modquery(
                        'update ignored set i_username = "%s" where i_username = "%s"' %
                        (iuser2, iuser1))
                    # update the list of ignored users
                    bot2.ignored = query(queries["ignoredusers"])
                    if not self.quiet:
                        self.msg(
                            "Changed the username of %s in the list of ignored users!" %
                            iuser1, target)
        else:
            if not self.quiet:
                self.msg(self.badsyntax, target)

    def do_stalked(self, cmd, target, nick):
        if cmd.lower().startswith("list"):
            stalkedpages = query(queries["stalkedpages"])
            self.msg("stalked pages: " + ", ".join(stalkedpages), target)
        elif cmd.lower().startswith("add"):
            who = re.sub("(?i)^add", "", cmd).strip(" ")
            who = who.split(" ")[0]
            who = who.replace("_", " ")
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a page name", target)
            else:
                who = who[0].upper() + who[1:]
                if len(
                    query(
                        'select f_page from followed where f_page="%s"' %
                        who)) > 0:
                    if not self.quiet:
                        self.msg("%s is already stalked!" % who, target)
                else:
                    modquery('insert into followed values (0, "%s")' % who)
                    # update the list of stalked pages
                    bot2.stalked = query(queries["stalkedpages"])
                    if not self.quiet:
                        self.msg(
                            "%s added to the list of stalked pages!" %
                            who, target)
        elif self.startswitharray(cmd.lower(), ["remove", "delete"]):
            who = re.sub("(?i)^(remove|delete)", "", cmd).strip(" ")
            who = who.split(" ")[0]
            who = who.replace("_", " ")
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a page name", target)
            else:
                who = who[0].upper() + who[1:]
                if len(
                    query(
                        'select f_page from followed where f_page="%s"' %
                        who)) == 0:
                    if not self.quiet:
                        self.msg(
                            "%s is not in the list of stalked pages!" %
                            who, target)
                else:
                    modquery('delete from followed where f_page="%s"' % who)
                    # update the list of stalked pages
                    bot2.stalked = query(queries["stalkedpages"])
                    if not self.quiet:
                        self.msg(
                            "%s removed from the list of stalked pages!" %
                            who, target)
        elif self.startswitharray(cmd.lower(), ["change", "edit", "modify", "rename"]):
            who = re.sub(
                "(?i)^(change|edit|modify|rename)",
                "",
                cmd).strip(" ")
            wholist = who.split(" ")
            if len(wholist) < 2:
                if not self.quiet:
                    self.msg("You have to specify two page names", target)
            else:
                ipage1 = wholist[0]
                ipage2 = wholist[1]
                ipage1 = ipage1[0].upper() + ipage1[1:]
                ipage2 = ipage2[0].upper() + ipage2[1:]
                ipage1 = ipage1.replace("_", " ")
                ipage2 = ipage2.replace("_", " ")
                if len(
                    query(
                        'select f_page from followed where f_page="%s"' %
                        ipage1)) == 0:
                    if not self.quiet:
                        self.msg(
                            "%s is not in the list of stalked pages!" %
                            ipage1, target)
                else:
                    modquery(
                        'update followed set f_page = "%s" where f_page = "%s"' %
                        (ipage2, ipage1))
                    # update the list of stalked pages
                    bot2.stalked = query(queries["stalkedpages"])
                    if not self.quiet:
                        self.msg(
                            "Changed the username of %s in the list of stalked pages!" %
                            ipage1, target)
        else:
            if not self.quiet:
                self.msg(self.badsyntax, target)

    def do_listen(self, cmd, target, nick):
        if cmd.lower().startswith("list"):
            listenedchannels = query(queries["listenedchannels"])
            self.msg(
                "'listen' channels: " +
                ", ".join(listenedchannels),
                target)
        elif cmd.lower().startswith("add"):
            who = re.sub("(?i)^add", "", cmd).strip(" ")
            who = who.split(" ")[0]
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a channel", target)
            else:
                if not who.startswith("#"):
                    who = "#" + who
                if len(
                    query(
                        'select l_channel from listen where l_channel="%s"' %
                        who)) > 0:
                    if not self.quiet:
                        self.msg(
                            "%s is already in the list of 'listen' channels!" %
                            who, target)
                else:
                    modquery('insert into listen values (0, "%s")' % who)
                    # update the list of listened channels
                    self.listened = query(queries["listenedchannels"])
                    if not self.quiet:
                        self.msg(
                            "%s added to the list of 'listen' channels!" %
                            who, target)
                    self.connection.join(who)
        elif self.startswitharray(cmd.lower(), ["remove", "delete"]):
            who = re.sub("(?i)^(remove|delete)", "", cmd).strip(" ")
            who = who.split(" ")[0]
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a channel", target)
            else:
                if not who.startswith("#"):
                    who = "#" + who
                if len(
                    query(
                        'select l_channel from listen where l_channel="%s"' %
                        who)) == 0:
                    if not self.quiet:
                        self.msg(
                            "%s is not in the list of 'listen' channels!" %
                            who, target)
                else:
                    modquery('delete from listen where l_channel="%s"' % who)
                    # update the list of listened channels
                    self.listened = query(queries["listenedchannels"])
                    if not self.quiet:
                        self.msg(
                            "%s removed from the list of 'listen' channels!" %
                            who, target)
                    self.connection.part(
                        who, "Requested by " + nick + " in " + self.channel)
        elif self.startswitharray(cmd.lower(), ["change", "edit", "modify", "rename"]):
            who = re.sub(
                "(?i)^(change|edit|modify|rename)",
                "",
                cmd).strip(" ")
            wholist = who.split(" ")
            if len(wholist) < 2:
                if not self.quiet:
                    self.msg("You have to specify two channels", target)
            else:
                chan1 = wholist[0]
                chan2 = wholist[1]
                if not chan1.startswith("#"):
                    chan1 = "#" + chan1
                if not chan2.startswith("#"):
                    chan2 = "#" + chan2
                if len(
                    query(
                        'select l_channel from listen where l_channel="%s"' %
                        chan1)) == 0:
                    if not self.quiet:
                        self.msg(
                            "%s is not in the list of stalked pages!" %
                            chan1, target)
                else:
                    modquery(
                        'update listen set l_channel = "%s" where l_channel = "%s"' %
                        (chan2, chan1))
                    # update the list of listened channels
                    bot2.stalked = query(queries["listenedchannels"])
                    if not self.quiet:
                        self.msg(
                            "Changed the name of %s in the list of 'listen' channels!" %
                            chan1, target)
                    self.connection.part(
                        chan1, "Requested by " + nick + " in " + self.channel)
                    self.connection.join(chan2)
        elif cmd.lower().startswith("on"):
            if not self.listen and self.listened:
                for chan in self.listened:
                    self.connection.join(chan)
                if not self.quiet:
                    self.msg("Joined the 'listen' channels.", target)
                self.listen = True
        elif cmd.lower().startswith("off"):
            if self.listen and self.listened:
                for chan in self.listened:
                    self.connection.part(chan)
                if not self.quiet:
                    self.msg("Parted the 'listen' channels.", target)
                self.listen = False
        else:
            if not self.quiet:
                self.msg(self.badsyntax, target)

    def do_steward(self, cmd, target, nick):
        if cmd.lower().startswith("users"):
            stewusers = query(queries["stewardusers"])
            self.msg("steward usernames: " + ", ".join(stewusers), nick)
        elif cmd.lower().startswith("nicks"):
            stewnicks = query(queries["stewardnicks"])
            self.msg("steward nicks: " + ", ".join(stewnicks), nick)
        elif cmd.lower().startswith("optin"):
            stewnicks = query(queries["stewardoptin"])
            self.msg("steward nicks: " + ", ".join(stewnicks), nick)
        elif cmd.lower().startswith("info"):
            who = re.sub("(?i)^info", "", cmd).strip(" ")
            who = who.split(" ")[0]
            who = who.replace("_", " ")
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a username", target)
            else:
                who = who[0].upper() + who[1:]
                stewinfo = query(
                    'select s_nick, s_cloak, s_optin from stewards where s_username="%s"' %
                    who, False)
                if len(stewinfo) == 0:
                    self.msg("%s is not a steward!" % who, target)
                else:
                    stewout = "Steward " + who
                    if stewinfo[0][0] is None:
                        stewout += " doesn't have a registered nickname on IRC."
                    else:
                        stewout += " uses nick " + stewinfo[0][0]
                        if stewinfo[0][1] is None:
                            stewout += " and doesn't have a cloak set"
                        else:
                            stewout += " with the cloak " + stewinfo[0][1]
                        if stewinfo[0][2] == 0:
                            soptin = "n't"
                        else:
                            soptin = ""
                        stewout += ". %s is%s in the list of opt-in nicks." % (stewinfo[0][
                                                                               0], soptin)
                    self.msg(stewout, target)
        elif cmd.lower().startswith("add"):
            who = re.sub("(?i)^add", "", cmd).strip(" ")
            who = re.sub(" +", " ", who)
            wholist = who.split(" ")
            wllen = len(wholist)
            if wllen == 0:
                if not self.quiet:
                    self.msg(
                        "You have to specify username, and optionally nick, cloak and opt-in preference",
                        target)
            else:
                suser = wholist[0]
                suser = suser[0].upper() + suser[1:]
                suser = suser.replace("_", " ")
                snick = "null"
                scloak = "null"
                soptin = "0"
                if wllen >= 2:
                    snick = '"%s"' % wholist[1]
                    if wllen >= 3:
                        if wholist[2] != "-":
                            scloak = '"%s"' % wholist[2].lower()
                        if wllen >= 4:
                            if wholist[3].lower() in ["yes", "true", "1"]:
                                soptin = "1"
                            elif wholist[3].lower() in ["no", "false", "0"]:
                                soptin = "0"
                if len(
                    query(
                        'select s_username from stewards where s_username="%s"' %
                        suser)) > 0:
                    if not self.quiet:
                        self.msg(
                            "%s is already in the list of stewards!" %
                            suser, target)
                else:
                    modquery(
                        'insert into stewards values (0, "%s", %s, %s, %s)' %
                        (suser, snick, scloak, soptin))
                    # update the list of steward nicks
                    self.steward = query(queries["stewardnicks"])
                    # update the list of steward opt-in nicks
                    self.optin = query(queries["stewardoptin"])
                    # update the list of privileged cloaks
                    self.privileged = query(queries["privcloaks"])
                    # update the list of ignored users
                    bot2.ignored = query(queries["ignoredusers"])
                    if not self.quiet:
                        self.msg(
                            "%s added to the list of stewards!" %
                            suser, target)
        elif self.startswitharray(cmd.lower(), ["remove", "delete"]):
            who = re.sub("(?i)^(remove|delete)", "", cmd).strip(" ")
            who = who.split(" ")[0]
            who = who.replace("_", " ")
            if not who:
                if not self.quiet:
                    self.msg("You have to specify a username", target)
            else:
                who = who[0].upper() + who[1:]
                if len(
                    query(
                        'select s_username from stewards where s_username="%s"' %
                        who)) == 0:
                    if not self.quiet:
                        self.msg("%s is not a steward!" % who, target)
                else:
                    modquery(
                        'delete from stewards where s_username="%s"' %
                        who)
                    # update the list of steward nicks
                    self.steward = query(queries["stewardnicks"])
                    # update the list of steward opt-in nicks
                    self.optin = query(queries["stewardoptin"])
                    # update the list of privileged cloaks
                    self.privileged = query(queries["privcloaks"])
                    # update the list of ignored users
                    bot2.ignored = query(queries["ignoredusers"])
                    if not self.quiet:
                        self.msg(
                            "%s removed from the list of stewards!" %
                            who, target)
        elif self.startswitharray(cmd.lower(), ["change", "edit", "modify", "rename"]):
            who = re.sub(
                "(?i)^(change|edit|modify|rename)",
                "",
                cmd).strip(" ")
            wholist = who.split(" ")
            wllen = len(wholist)
            if wllen < 2:
                if not self.quiet:
                    self.msg(
                        "You have to specify two usernames, and optionally nick, cloak and opt-in preference",
                        target)
            else:
                suser1 = wholist[0]
                suser2 = wholist[1]
                suser1 = suser1.replace("_", " ")
                suser2 = suser2.replace("_", " ")
                setlist = []
                if suser2 != "-":
                    setlist += ['s_username = "%s"' % suser2]
                if wllen >= 3:
                    if wholist[2] != "-":
                        setlist += ['s_nick = "%s"' % wholist[2]]
                    if wllen >= 4:
                        if wholist[3] != "-":
                            setlist += ['s_cloak = "%s"' % wholist[3].lower()]
                        if wllen >= 5:
                            if wholist[4].lower() in ["yes", "true", "1"]:
                                setlist += ['s_optin = 1']
                            elif wholist[4].lower() in ["no", "false", "0"]:
                                setlist += ['s_optin = 0']
                if len(
                    query(
                        'select s_username from stewards where s_username="%s"' %
                        suser1)) == 0:
                    if not self.quiet:
                        self.msg("%s is not a steward!" % suser1, target)
                else:
                    if len(setlist) == 0:
                        if not self.quiet:
                            self.msg("No change necessary!")
                    else:
                        modquery(
                            'update stewards set %s where s_username = "%s"' %
                            (", ".join(setlist), suser1))
                        # update the list of steward nicks
                        self.steward = query(queries["stewardnicks"])
                        # update the list of steward opt-in nicks
                        self.optin = query(queries["stewardoptin"])
                        # update the list of privileged cloaks
                        self.privileged = query(queries["privcloaks"])
                        # update the list of ignored users
                        bot2.ignored = query(queries["ignoredusers"])
                        if not self.quiet:
                            self.msg(
                                "Updated information for steward %s!" %
                                suser1, target)
        else:
            if not self.quiet:
                self.msg(self.badsyntax, target)

    def msg(self, poruka, target=None):
        if not target:
            target = self.channel
        try:
            self.connection.privmsg(target, poruka)
        except irc.client.MessageTooLong:
            self.connection.privmsg(
                target,
                "The message is too long. Please fill a task in Phabricator under #stewardbots describing what you tried to do."
            )

    def getcloak(self, doer):
        if re.search("/", doer) and re.search("@", doer):
            return doer.split("@")[1]

    def startswitharray(self, text, array):
        for entry in array:
            if text.startswith(entry):
                return True
        return False


class WikimediaBot():
    def __init__(self):
        self.stalked = query(queries["stalkedpages"])
        self.ignored = query(queries["ignoredusers"])
        self.RE_SECTION = re.compile(r"/\* *(?P<section>.+?) *\*/", re.DOTALL)

    def run(self):
        stream = 'https://stream.wikimedia.org/v2/stream/recentchange'
        for event in EventSource(stream):
            if bot1.quiet:
                continue

            if event.event == 'message':
                try:
                    change = json.loads(event.data)
                except ValueError:
                    continue
                if change['wiki'] == 'metawiki':
                    if change['bot']:
                        continue

                    if change['type'] == 'edit':
                        if change['title'] not in self.stalked:
                            continue

                        if change['user'] in self.ignored:
                            continue

                        rccomment = change['comment'].strip()
                        m = self.RE_SECTION.search(rccomment)
                        if m:
                            section = "#" + m.group('section')
                        else:
                            section = ""
                        comment = " with the following comment: 07" + \
                            rccomment.strip(" ") + ""
                        bot1.msg(
                            "03%s edited 10[[%s%s]] 02https://meta.wikimedia.org/wiki/Special:Diff/%s%s" %
                            (change['user'], change['title'], section, change['id'], comment))
                    elif change['type'] == "log":
                        if change['log_type'] == "rights":
                            performer = change['user']
                            target = change['title'].replace('User:', '')
                            selff = ""
                            bott = ""
                            if performer == target:
                                selff = "06(self) "
                            if "bot" in change['log_params']['newgroups'] or "bot" in change['log_params']['oldgroups']:
                                bott = "06(bot) "

                            # construct from_rights
                            from_rights = []
                            for i in range(len(change['log_params']['oldgroups'])):
                                group = change['log_params']['oldgroups'][i]
                                if change['log_params']['oldmetadata'][i] == []:
                                    from_rights.append(group)
                                else:
                                    expiry = datetime.strptime(change['log_params']['oldmetadata'][i]['expiry'], '%Y%m%d%H%M%S')
                                    from_rights.append('%s (expiry: %s)' % (group, expiry.strftime('%H:%M, %d %B %Y')))

                            # construct to_rights
                            to_rights = []
                            for i in range(len(change['log_params']['newgroups'])):
                                group = change['log_params']['newgroups'][i]
                                metadata = change['log_params']['newmetadata'][i]
                                if metadata == []:
                                    to_rights.append(group)
                                else:
                                    expiry = datetime.strptime(metadata['expiry'], '%Y%m%d%H%M%S')
                                    to_rights.append('%s (expiry: %s)' % (group, expiry.strftime('%H:%M, %d %B %Y')))

                            from_rights_text = "(none)"
                            if len(from_rights) > 0:
                                from_rights_text = ", ".join(from_rights)

                            to_rights_text = "(none)"
                            if len(to_rights) > 0:
                                to_rights_text = ", ".join(to_rights)
                            bot1.msg(
                                "%s%s03%s changed user rights for %s from 04%s to 04%s: 07%s" % (
                                    selff,
                                    bott,
                                    performer,
                                    target,
                                    from_rights_text,
                                    to_rights_text,
                                    change['comment']
                                )
                            )
                        elif change['log_type'] == "gblblock":
                            target = change['title'].replace('User:', '')
                            performer = change['user']
                            expiry = ''
                            comment = " with the following comment: 7" + \
                                change['comment'].strip(" ") + ""
                            if change['log_action'] == 'gblock2':
                                expiry = change['log_params'][0]
                                action_description = 'globally blocked'
                            elif change['log_action'] == 'gunblock':
                                action_description = 'removed global block on'
                            else:
                                action_description = 'modified the global block on'
                            bot1.msg(
                                "03%s %s %s (%s) %s" %
                                (performer, action_description, target, expiry, comment)
                            )
                        elif change['log_type'] == 'globalauth':
                            target = change['title'].replace('User:', '').replace('@global', '').strip()
                            comment = change['comment']
                            if comment != "":
                                comment = "with the following comment: 07" + \
                                    comment.strip(" ") + ""

                            if change['log_params'][0] == 'locked':
                                action_description = 'locked global account'
                            else:
                                action_description = 'unlocked global account'

                            bot1.msg("03%s %s %s %s" % (change['user'], action_description, target, comment))
                        elif change['log_type'] == 'gblrights':
                            target = change['title'].replace('User:', '')
                            bot1.msg(
                                "03%s changed global group membership for %s from 04%s to 04%s: 07%s" %
                                (
                                    change['user'],
                                    target,
                                    change['log_params'][0],
                                    change['log_params'][1],
                                    change['comment']
                                )
                            )


class IgnoreErrorsBuffer(buffer.DecodingLineBuffer):
    def handle_exception(self):
        pass


class BotThread(threading.Thread):

    def __init__(self, bot):
        self.b = bot
        threading.Thread.__init__(self)

    def run(self):
        self.startbot(self.b)

    def startbot(self, bot):
        ServerConnection.buffer_class = IgnoreErrorsBuffer
        bot.start()


class RecentChangesThread(threading.Thread):
    def __init__(self, bot):
        self.b = bot
        threading.Thread.__init__(self)

    def run(self):
        self.b.run()


def main():
    global bot1, bot2
    bot1 = FreenodeBot()
    bot2 = WikimediaBot()
    try:
        BotThread(bot1).start()
        RecentChangesThread(bot2).start()  # can raise ServerNotConnectedError
    except KeyboardInterrupt:
        raise


if __name__ == "__main__":
    global bot1, bot2
    try:
        main()
    except IOError:
        print("No config file! You should start this script from its directory like 'python stewardbot.py'")
    finally:
        bot1.die()
        bot2.die()
        sys.exit()
