import bs4
import sys
import requests
import re
import json

POSTS_PER_PAGE = 20
CONFIG_FILE = "config.json"
output_filepath = "out.txt"

Soup = bs4.BeautifulSoup


def parse_thread(url):
    posts = []

    soup = Soup(requests.get(url).text, "html.parser")

    num_posts = int(re.search("(\d+) posts", str(soup.find("div", {"class": "pagination"}))).group(1))

    game_num = re.search("\d+", str(soup.find("title"))).group()

    # first page... need to request anyway to see how many pages we have
    posts += soup.findAll("div", {"class": "content"})

    for page_num in range(0, num_posts, POSTS_PER_PAGE):
        if page_num > 0:
            # all subsequent pages
            soup = Soup(requests.get(url + "&start=" + str(page_num)).text, "html.parser")

            posts += soup.findAll("div", {"class": "content"})

    # clean up the posts
    posts = [x.get_text("\n") for x in posts]

    return [game_num, posts]


def build_scores(thread_info):
    with open(CONFIG_FILE) as config_file:
        config = json.load(config_file)
        players = config["players"]
        global output_filepath
        try:
            output_filepath = config["output-filepath"]
        except KeyError:
            pass

    [game_num, posts] = thread_info

    # process the posts
    for post in posts:
        # get votes
        votes = re.findall("(-?[0-3](?:.[0-9]+)?)\W*\s+([A-Z]+.*)", str(post))

        # prompt the user for each post
        prompt(post, votes, players)

    # sort the players
    players = sorted(players, key=lambda p: get_score(p), reverse=True)

    # and add to out.txt
    with open(output_filepath, "a") as text:
        text.write("Game " + game_num + "\n")

        for player in players:
            text.write(player["firstname"] + " " + player["lastname"] + " " + str(get_score(player)) + "\n")
        text.write("\n")


def get_score(player):
    try:
        return float(player["score"])
    except KeyError:
        return 0


def apply_score(guesses):
    for guess in guesses:
        player = guess["player"]
        try:
            player["score"] += guess["score"]
        except KeyError:
            player["score"] = guess["score"]


def match_player(player_string, players):
    for player in players:
        if player_string in player["aliases"] or player_string == player["lastname"]:
            return player
    return None


def best_guesses(votes, players):
    guesses = []
    for (score_str, player_str_array) in votes:
        for player_str in player_str_array.split(" "):
            player = match_player(player_str, players)
            if player is not None:
                guesses.append({"player": player, "score": float(score_str)})
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

    guesses = sorted(guesses, key=lambda g: g["score"], reverse=True)
    for guess in guesses:
        print (str(int(guess["score"])) if guess["score"].is_integer() else "%.1f" % guess["score"]) + " " + \
              guess["player"]["firstname"] + " " + guess["player"]["lastname"]


def prompt(post, votes, players):
    print "********************\n" + post + "\n********************"

    guesses = best_guesses(votes, players)

    while True:

        print_guesses(guesses)

        inp = raw_input("")

        match = re.match("(\w+)\s*(\d+)?\s*(-?[0-3](?:.[0-9]+)?)?", inp)

        if match is None:
            continue

        (cmd, pid, value) = match.group(1, 2, 3)

        if cmd == "c" or cmd == "confirm":
            apply_score(guesses)
            return
        elif cmd == "s" or cmd == "skip":
            return
        elif cmd == "a" or cmd == "add":
            player = get_player(int(pid), players)
            if player is None:
                print "Player does not exist"
                continue
            guesses.append({"player": player, "score": float(value)})
        elif cmd == "r" or cmd == "remove":
            for guess in guesses:
                if guess["player"]["id"] == int(pid):
                    guesses.remove(guess)
                    break
        elif cmd == "p" or cmd == "players":
            for player in players:
                print str(player["id"]) + " " + player["firstname"] + " " + player["lastname"]
        elif cmd == "q":
            sys.exit(0)


def main():
    url = raw_input("URL please ")

    thread_info = parse_thread(url)

    build_scores(thread_info)


main()
