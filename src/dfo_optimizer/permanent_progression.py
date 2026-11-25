"""Validate an attributed Firmament tree and compile funded additive edges into compact state IDs."""
from .progression_domain import Gap, evidence, fields, integer
from .progression_replay import require


class Firmament:
    def __init__(self, observation, rules, character_id):
        self.nodes = rules.get("nodes", {})
        self.starts = set(rules.get("starts", ()))
        self.ids = {}
        self.states = []
        self.initial = None
        self.stars = self.craft = 0
        self.access = False
        if observation is None:
            return
        fields(observation, {"tree", "renown", "profession_ranks", "source", "observed_at_ms",
                             "access", "character_id"}, "Firmament observation")
        evidence(observation.get("source"))
        integer(observation.get("observed_at_ms"), "Firmament observation timestamp", 0, 2**53-1)
        require(isinstance(character_id, str) and character_id and observation.get("character_id") == character_id,
                "Firmament observation requires the matching saved character")
        require(self.nodes and self.starts, "Firmament requires the verified permanent progression catalog")
        require(type(observation.get("access")) is bool, "Firmament access must be observed")
        self.access = observation["access"]
        renown = integer(observation.get("renown"),"observed Renown",1,rules["renown_max"])
        ranks = observation.get("profession_ranks")
        require(isinstance(ranks, list) and len(ranks) == 10, "Firmament requires ten profession ranks")
        self.craft = sum(integer(r, "profession rank", 0, 100) for r in ranks) // rules["craft_ranks_per_point"]
        self.stars = (renown - 1) * rules["stars_per_renown"]
        self.initial = self.identify(observation.get("tree"))
        require(self.fits(self.states[self.initial]), "observed Firmament tree exceeds its points")

    def identify(self, tree):
        fields(tree, ("start","keys"), "Firmament tree")
        start, keys = tree.get("start"), tree.get("keys")
        require((start is None or isinstance(start,str) and start in self.starts) and isinstance(keys,list),
                "invalid Firmament sign or keys")
        require(all(isinstance(k,str) and k in self.nodes and k not in self.starts for k in keys)
                and len(keys) == len(set(keys)), "invalid or repeated Firmament star")
        identity = (start, tuple(sorted(keys)))
        if identity in self.ids:
            return self.ids[identity]
        held = set(keys)
        frontier = [start] if start else []
        visited = set(frontier)
        while frontier:
            current = frontier.pop()
            if self.nodes[current]["kind"] == "keystone":
                continue
            for adjacent in self.nodes[current]["adjacent"]:
                if adjacent in held and adjacent not in visited:
                    visited.add(adjacent)
                    frontier.append(adjacent)
        require(held <= visited, "Firmament stars must be connected through their sign")
        life = sum(self.nodes[k]["ring"] == "life" for k in keys)
        craft_used = min(life, self.craft)
        state = {"tree":{"start":start, "keys":list(identity[1])}, "stars_left":self.stars-len(keys)+craft_used,
                 "craft_left":self.craft-craft_used}
        index = len(self.states)
        self.ids[identity] = index
        self.states.append(state)
        return index

    @staticmethod
    def fits(state):
        return state["stars_left"] >= 0 and state["craft_left"] >= 0

    def edge(self, action):
        if not self.access:
            raise Gap("Firmament allocation requires observed account access for this character")
        tree = action.get("from")
        before = self.identify(tree)
        node = action.get("node")
        require(isinstance(node,str) and node in self.nodes, "unknown Firmament node")
        if node in self.starts:
            if tree["start"] is not None:
                raise Gap("changing an existing Firmament sign requires a paid respec")
            after = self.identify({"start":node,"keys":[]})
        else:
            if node in tree["keys"] or not tree["start"]:
                raise Gap("Firmament requires a new star and a chosen sign")
            try:
                after = self.identify({"start":tree["start"], "keys":[*tree["keys"],node]})
            except ValueError as exc:
                raise Gap(str(exc)) from exc
        if not self.fits(self.states[after]):
            raise Gap("insufficient observed Firmament points for the new star")
        return {"firm_from":before, "firm_to":after}
