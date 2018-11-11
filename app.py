import bs4
import sys
import requests
import re
import json
from scipy import stats
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import urllib3


POSTS_PER_PAGE = 20
CONFIG_FILE = "config.json"
SHEET_CRED = "creds.json"
output_filepath = "out.txt"

Soup = bs4.BeautifulSoup


def parse_thread(url):
    posts = []

    urllib3.disable_warnings()
    r = requests.get(url, verify=False)

    soup = Soup(r.text, "html.parser")

    num_posts = int(re.search("(\d+) posts", str(soup.find("div", {"class": "pagination"}))).group(1))

    game_num = int(re.search("\d+", str(soup.find("title"))).group())

    # first page... need to request anyway to see how many pages we have
    posts += soup.findAll("div", {"class": "content"})

    for page_num in range(0, num_posts, POSTS_PER_PAGE):
        if page_num > 0:
            # all subsequent pages
            soup = Soup(requests.get(url + "&start=" + str(page_num), verify=False).text, "html.parser")

            posts += soup.findAll("div", {"class": "content"})

    # clean up the posts
    posts = [x.get_text("\n") for x in posts]

    return [game_num, posts]


def build_votes(thread_info, margin):
    with open(CONFIG_FILE) as config_file:
        # load the config file and pull the players
        config = json.load(config_file)
        players = config["players"]

        # initialise the votes
        for player in players:
            player["vote"] = 0

        global output_filepath
        try:
            output_filepath = config["output-filepath"]
        except KeyError:
            pass
        try:
            score_settings = config["scoring"]
            sheet_settings = config["sheet"]
        except KeyError:
            pass

    [game_num, posts] = thread_info

    # process the posts
    for post in posts:
        # get all votes

        # vote score ahead (standard)
        print re.findall("([+-]?[0-3]?(?:.[0-9]+)?)\W*[ \t]+([A-Z]+.*)", str(post.encode('ascii','ignore')))

        votes = re.findall("([+-]?[0-9]?(?:.[0-9]+)?)\W*[ \t]+(?:for |to )?([A-z]+)", str(post.encode('ascii','ignore')))
        print votes
        # vote score trailing
        votes += re.findall("([A-z]+)\W*[ \t]+([+-]?[0-9]?(?:.[0-9]+)?)", str(post.encode('ascii','ignore')))

        # prompt the user for each post
        prompt(post, votes, players, margin)

    # sort the players
    players = sorted(players, key=lambda p: get_vote(p), reverse=True)

    # now we pump it into the sheet
    push2sheet(players, game_num, score_settings, sheet_settings, margin)

    # and add to out.txt
    with open(output_filepath, "a") as text:
        text.write("Game " + str(game_num) + "\n")

        for player in players:
            text.write(player["firstname"] + " " + player["lastname"] + " Votes: " + str(player["vote"])
                       + " Score: " + str(player["score"]) + "\n")
        text.write("\n")


def get_vote(player):
    try:
        return float(player["vote"])
    except KeyError:
        return 0


def apply_votes(guesses):
    for guess in guesses:
        player = guess["player"]
        try:
            player["vote"] += guess["vote"]
        except KeyError:
            player["vote"] = guess["vote"]


def match_player(player_string, players):
    for player in players:
        if player_string.lower() in [x.lower() for x in player["aliases"]] \
                or player_string.lower() == player["lastname"].lower():
            return player
    return None


def best_guesses(votes, players, margin):
    guesses = []
    for vote in votes:
        try:
            float(vote[0])  # cast to check if vote ahead or vote behind
            (vote_str, player_str_array) = (vote[0], vote[1])
        except ValueError:
            try:
                float(vote[1])  # confirm vote behind
                (vote_str, player_str_array) = (vote[1], vote[0])
            except ValueError:
                # this is not an actual vote
                continue
        if float(vote_str) < 0 < margin:
            # can't have a negative vote in wins
            continue
        if float(vote_str) > 3:
            vote_str = 3
        if float(vote_str) < -3:
            vote_str = -3
        for player_str in player_str_array.split(" "):
            player = match_player(player_str, players)
            if player is not None:
                guesses.append({"player": player, "vote": float(vote_str)})
                break

    return guesses


def get_player(pid, players):
    for player in players:
        if player["id"] == pid:
            return player
    return None


def print_guesses(guesses):
    print "Parsed votes:"
    print "********************"

    guesses = sorted(guesses, key=lambda g: g["vote"], reverse=True)
    for guess in guesses:
        print (str(int(guess["vote"])) if guess["vote"].is_integer() else "%.2f" % guess["vote"]) + " " + \
              guess["player"]["firstname"] + " " + guess["player"]["lastname"]


def push2sheet(players, game_number, score_settings, sheet_settings, margin=0):

    generate_scores(players, score_settings, margin)

    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

    credentials = ServiceAccountCredentials.from_json_keyfile_name(SHEET_CRED, scope)
    gc = gspread.authorize(credentials)
    standings = gc.open("NASHTY & CACTUS - 2018-19").worksheet("standings")

    row = game_number - 1 + sheet_settings["row_start"]
    off_col = sheet_settings["col_start"]

    for player in players:
        col = player["id"] - 1 + off_col
        if standings.cell(row,col).value == "":
            standings.update_cell(row,col, player["score"])
        else:
            print "Error - already have value in cell"


def generate_scores(players, score_settings, margin):
    print margin

    z_score_neg = score_settings["z_score_neg"]
    z_score_pos = score_settings["z_score_pos"]
    default_score = score_settings["default_score"]
    scale_distance = score_settings["scale_distance"]
    max_scale_score = score_settings["max_scale_score"]
    scale_adjust = scale_distance*(float(margin)/max_scale_score)
    print scale_adjust

    players = sorted(players, key=lambda g: g["vote"], reverse=True)
    z_scores = stats.zscore([player["vote"] for player in players])
    print z_scores
    trim_z = [x if x < z_score_neg or x > z_score_pos else 0 for x in z_scores]
    a = [n for n in trim_z if n > 0]
    b = [n for n in trim_z if n < 0]
    for i in range(len(trim_z)):
        if trim_z[i] != 0:
            if trim_z[i] in a:
                players[i]["score"] = trim_z[i] * (default_score + scale_adjust) / sum(a)
            elif trim_z[i] in b and margin < 0:
                players[i]["score"] = trim_z[i] * (-default_score + scale_adjust) / sum(b)
            else:
                players[i]["score"] = 0
        else:
            players[i]["score"] = 0

    for player in players:
        print player


def prompt(post, votes, players, margin):

    print "********************\n" + post.encode('utf-8') + "\n********************"

    guesses = best_guesses(votes, players, margin)

    while True:

        print_guesses(guesses)

        inp = raw_input("")

        match = re.match("(\w+)\s*(\d+)?\s*(-?[0-3](?:.[0-9]+)?)?", inp)

        if match is None:
            continue

        (cmd, pid, value) = match.group(1, 2, 3)

        if cmd == "c" or cmd == "confirm":
            apply_votes(guesses)
            return
        elif cmd == "s" or cmd == "skip":
            return
        elif cmd == "a" or cmd == "add":
            player = get_player(int(pid), players)
            if player is None:
                print "Player does not exist"
                continue
            guesses.append({"player": player, "vote": float(value)})
        elif cmd == "r" or cmd == "remove":
            for guess in guesses:
                if guess["player"]["id"] == int(pid):
                    guesses.remove(guess)
                    break
        elif cmd == "p" or cmd == "players":
            for player in players:
                print str(player["id"]) + " " + player["firstname"] + " " + player["lastname"]
        elif cmd == "cl":
            guesses = []
        elif cmd == "q":
            sys.exit(0)


def main():
    url = raw_input("URL please ")

    thread_info = parse_thread(url)

    margin = int(raw_input("Margin please "))

    build_votes(thread_info, margin)


main()
