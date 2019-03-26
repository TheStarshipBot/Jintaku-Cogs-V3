import discord
from redbot.core import Config, checks, commands
from redbot.core.utils.menus import menu, commands, DEFAULT_CONTROLS
import aiohttp
import contextlib
from random import randint
import asyncio
import logging
from aiocache import cached, SimpleMemoryCache

cache = SimpleMemoryCache()

log = logging.getLogger("BooruCore")  # Thanks to Sinbad for the example code for logging
log.setLevel(logging.DEBUG)

console = logging.StreamHandler()

if logging.getLogger("red").isEnabledFor(logging.DEBUG):
    console.setLevel(logging.DEBUG)
else:
    console.setLevel(logging.INFO)
log.addHandler(console)

class BooruCore:

    async def generic_booru(self, ctx, tag):

        tag = await self.filter_tags(ctx, tag)

        if tag is None:
            return

        log.debug(tag)

        # Image board fetcher
        guild_boards = await self.config.guild(ctx.guild).boards()
        channel_boards = await self.config.channel(ctx.channel).boards()

        if set(channel_boards) == {"dan", "gel", "kon", "yan"}:
            boards = guild_boards
        else:
            boards = channel_boards

        if boards == []:
            await ctx.send("There no image boards, please use [p]booruset guild boards to set them.")
            return

        all_data = await asyncio.gather(*(getattr(self, f"fetch_{board}")(ctx, tag) for board in boards))
        data = [item for board_data in all_data for item in board_data]

        # Filter data without using up requests space
        data = await self.filter_posts(ctx, data)

        # Done sending requests, time to show it
        await self.show_booru(ctx, data)

    async def generic_alias_booru(self, ctx, boards, tag):

        tag = await self.filter_tags(ctx, tag)

        if tag is None:
            return

        log.debug(tag)

        all_data = await asyncio.gather(*(getattr(self, f"fetch_{board}")(ctx, tag) for board in boards))
        data = [item for board_data in all_data for item in board_data]

        # Filter data without using up requests space
        data = await self.filter_posts(ctx, data)

        # Done sending requests, time to show it
        await self.show_booru(ctx, data)

    async def generic_specific_source(self, ctx, board, tag):
        """Shows a image board entry based on user query from a specific source"""

        tag = await self.filter_tags(ctx, tag)

        if tag is None:
            return

        log.debug(tag)

        # Image board fetcher
        data = await getattr(self, f"fetch_{board}")(ctx, tag)

        # Filter data without using up requests space
        data = await self.filter_posts(ctx, data)

        # Done sending requests, time to show it
        await self.show_booru(ctx, data)

    async def filter_tags(self, ctx, tag):
        # Checks if there is a tag and defaults depending on channel
        if tag is not None:
            tag = set(tag.split(" "))
        if ctx.channel.is_nsfw() and tag is None:
            tag = {"rating:none", "*"}
        if ctx.channel.is_nsfw() and tag is not None:
            tag.add("rating:none")
        if ctx.channel.is_nsfw() == False and tag is None:
            tag = {"rating:safe", "*"}

        log.debug(tag)

        # Checks common to see if any ratings are there
        ratings = {"rating:safe", "rating:explicit", "rating:questionable", "rating:none"}
        if not ratings & tag:
            tag.add("rating:safe")

        # Checks if none and removes ratings
        if "rating:none" in tag:
            tag.remove("rating:none")

        # Checks if nsfw could be posted in sfw channel
        if not ctx.channel.is_nsfw():

            # Respect onlynsfw setting
            nsfw_booru = await self.config.guild(ctx.guild).onlynsfw()
            if nsfw_booru == "on":
                await ctx.send("You cannot use booru in sfw channels")
                return

            if "rating:explicit" in tag or "rating:questionable" in tag or not ratings & tag:
                await ctx.send("You cannot post nsfw content in sfw channels")
                return

        # Checks if more than 6 tag and tells user you can't do that
        if len(tag) > 6:
            await ctx.send("You cannot search for more than 6 tags at once")
            return

        log.debug(tag)

        return tag

    async def filter_posts(self, ctx, data):
        # Global filters
        global_filters = set(await self.config.filters())
        global_nsfw_filters = set(await self.config.nsfw_filters())

        # Guild filters
        guild_group = self.config.guild(ctx.guild)
        guild_nsfw_filters = set(await guild_group.nsfw_filters())
        guild_filters = set(await guild_group.filters())

        # Fuse both global and guild for cleaner use
        filters = global_filters | guild_filters
        nsfw_filters = global_nsfw_filters | guild_nsfw_filters

        # Set variable because
        filtered_data = []

        # Filter the content
        for booru in data:
            booru_tags_string = booru.get("tags") or booru.get("tag_string") or "N/A"
            booru_tags = set(booru_tags_string.split())

            if booru["rating"] in "sqe":
                if filters & booru_tags or (booru["rating"] != "s" and nsfw_filters & booru_tags):
                    continue
            if booru.get("is_deleted"):
                continue
            if booru["provider"] == "Danbooru" and "file_url" not in booru:
                continue

            filtered_data.append(booru)

        return filtered_data

    async def fetch_from_reddit(self, urlstr, rating, provider):  # Handles provider data and fetcher responses
        content = ""

        async with aiohttp.ClientSession() as session:
            async with session.get(urlstr, headers={'User-Agent': "Booru (https://github.com/Jintaku/Jintaku-Cogs-V3)"}) as resp:
                try:
                    content = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as ex:
                    log.debug("Pruned by exception, error below:")
                    log.debug(ex)
                    content = []
        if not content or content == [] or content is None or (type(content) is dict and "success" in content.keys() and content["success"] == False):
            content = []
            return content
        else:
            for item in content["data"]["children"]:
                item["provider"] = provider
                item["rating"] = rating
        return content["data"]["children"]


    @cached(ttl=3600, cache=SimpleMemoryCache, key="4k")
    async def fetch_4k(self, ctx, tag):  # 4k fetcher
        subreddits = ["HighResNSFW", "UHDnsfw", "nsfw4k", "nsfw_hd", "NSFW_Wallpapers", "HDnsfw", "closeup"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="ahegao")
    async def fetch_ahegao(self, ctx, tag):  # ahegao fetcher
        subreddits = ["AhegaoGirls", "RealAhegao", "EyeRollOrgasm", "MouthWideOpen"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="ass")
    async def fetch_ass(self, ctx, tag):  # ass fetcher
        subreddits = ["ass", "pawg", "AssholeBehindThong", "girlsinyogapants", "girlsinleggings", "bigasses", "asshole", "AssOnTheGlass", "TheUnderbun", "asstastic", "booty", "AssReveal", "beautifulbutt", "Mooning", "BestBooties", "brunetteass", "assinthong", "paag", "asstastic", "GodBooty", "Underbun", "datass", "ILikeLittleButts"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="anal")
    async def fetch_anal(self, ctx, tag):  # anal fetcher
        subreddits = ["MasterOfAnal", "analgonewild", "anal", "buttsex", "buttsthatgrip", "AnalGW", "analinsertions", "AnalGW", "assholegonewild"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="bdsm")
    async def fetch_bdsm(self, ctx, tag):  # bdsm fetcher
        subreddits = ["BDSMGW", "bdsm", "ropeart", "shibari"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="blowjob")
    async def fetch_blowjob(self, ctx, tag):  # blowjob fetcher
        subreddits = ["blowjobsandwich", "Blowjobs", "BlowjobGifs", "BlowjobEyeContact", "blowbang", "AsianBlowjobs", "SuckingItDry", "OralCreampie", "SwordSwallowers"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="boobs")
    async def fetch_boobs(self, ctx, tag):  # boobs fetcher
        subreddits = ["boobs", "TheHangingBoobs", "bigboobs", "BigBoobsGW", "hugeboobs", "pokies", "ghostnipples", "PiercedNSFW", "piercedtits", "PerfectTits", "BestTits", "Boobies", "JustOneBoob", "tits", "naturaltitties", "smallboobs", "Nipples", "homegrowntits", "TheUnderboob", "BiggerThanYouThought", "fortyfivefiftyfive", "Stacked", "BigBoobsGonewild", "AreolasGW", "TittyDrop", "Titties", "Boobies", "boobbounce", "TinyTits", "cleavage", "BoobsBetweenArms","BustyNaturals"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="cunnilingus")
    async def fetch_cunnilingus(self, ctx, tag):  # cunnilingus fetcher
        subreddits = ["cunnilingus", "CunnilingusSelfie", "Hegoesdown"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="bottomless")
    async def fetch_bottomless(self, ctx, tag):  # bottomless fetcher
        subreddits = ["upskirt", "Bottomless", "Bottomless_Vixens", "nopanties", "Pantiesdown"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="cumshots")
    async def fetch_cumshots(self, ctx, tag):  # cumshots fetcher
        subreddits = ["OralCreampie", "cumfetish", "cumontongue", "cumshots", "CumshotSelfies", "facialcumshots", "pulsatingcumshots", "gwcumsluts", "ImpresssedByCum", "GirlsFinishingTheJob", "cumshot", "amateurcumsluts", "unexpectedcum", "bodyshots", "ContainTheLoad", "bodyshots"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="deepthroat")
    async def fetch_deepthroat(self, ctx, tag):  # deepthroat fetcher
        subreddits = ["DeepThroatTears", "deepthroat", "SwordSwallowers"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="dick")
    async def fetch_dick(self, ctx, tag):  # dick fetcher
        subreddits = ["DickPics4Freedom", "mangonewild", "MassiveCock", "penis", "cock", "ThickDick"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="doublepenetration")
    async def fetch_double_penetration(self, ctx, tag):  # double penetration fetcher
        subreddits = ["doublepenetration", "dp_porn", "Technical_DP"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="gay")
    async def fetch_gay(self, ctx, tag):  # gay fetcher
        subreddits = ["gayporn", "GayPornForStrtGuys", "ladybonersgw", "mangonewild"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="group")
    async def fetch_group(self, ctx, tag):  # group fetcher
        subreddits = ["GroupOfNudeGirls", "GroupOfNudeMILFs", "groupsex"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="hentai")
    async def fetch_hentai(self, ctx, tag):  # hentai fetcher
        subreddits = ["hentai", "thick_hentai", "HQHentai", "AnimeBooty", "thighdeology", "ecchigifs", "nsfwanimegifs", "oppai_gif"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="lesbian")
    async def fetch_lesbian(self, ctx, tag):  # lesbian fetcher
        subreddits = ["lesbians", "HDLesbianGifs", "amateurlesbians", "Lesbian_gifs"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="milf")
    async def fetch_milf(self, ctx, tag):  # milf fetcher
        subreddits = ["amateur_milfs", "GroupOfNudeMILFs", "ChocolateMilf", "milf", "Milfie", "hairymilfs", "HotAsianMilfs", "HotMILFs", "MILFs", "maturemilf", "puremilf", "amateur_milfs"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="public")
    async def fetch_public(self, ctx, tag):  # public fetcher
        subreddits = ["RealPublicNudity", "FlashingAndFlaunting", "FlashingGirls", "PublicFlashing", "Unashamed", "OutsideNude", "NudeInPublic", "publicplug", "casualnudity"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="rule34")
    async def fetch_rule34(self, ctx, tag):  # rule34 fetcher
        subreddits = ["rule34", "rule34cartoons", "Rule_34", "Rule34LoL", "AvatarPorn", "Overwatch_Porn", "Rule34Overwatch", "WesternHentai"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="thigh")
    async def fetch_thigh(self, ctx, tag):  # thigh fetcher
        subreddits = ["Thighs", "ThickThighs", "thighhighs", "Thigh", "leggingsgonewild"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="trap")
    async def fetch_trap(self, ctx, tag):  # trap fetcher
        subreddits = ["Transex", "DeliciousTraps", "traps", "trapgifs", "GoneWildTrans", "SexyShemales", "Shemales", "shemale_gifs", "Shemales", "ShemalesParadise", "Shemale_Big_Cock", "ShemaleGalleries"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    @cached(ttl=3600, cache=SimpleMemoryCache, key="wild")
    async def fetch_wild(self, ctx, tag):  # wild fetcher
        subreddits = ["gonewild", "GWNerdy", "dirtysmall", "MyCalvins", "AsiansGoneWild", "GoneWildSmiles", "gonewildcurvy", "BigBoobsGonewild", "gonewildcouples", "gonewildcolor", "PetiteGoneWild", "GWCouples", "BigBoobsGW", "altgonewild", "LabiaGW", "UnderwearGW", "JustTheTop", "TallGoneWild", "LingerieGW", "Swingersgw"]
        all_content = []
        for subreddit in subreddits:
            urlstr = "https://reddit.com/r/" + subreddit + "/new.json?limit=100"
            log.debug(urlstr)
            content = await self.fetch_from_reddit(urlstr, "explicit", "Reddit")
            all_content.extend(content)
        return all_content

    async def fetch_from_booru(self, urlstr, provider):  # Handles provider data and fetcher responses
        content = ""

        # TODO : Use aiohttp clientsession in init to be reused
        async with aiohttp.ClientSession() as session:
            async with session.get(urlstr, headers={'User-Agent': "Booru (https://github.com/Jintaku/Jintaku-Cogs-V3)"}) as resp:
                try:
                    content = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as ex:
                    log.debug("Pruned by exception, error below:")
                    log.debug(ex)
                    content = []
        if not content or content == [] or content is None or (type(content) is dict and "success" in content.keys() and content["success"] == False):
            content = []
            return content
        else:
            for item in content:
                item["provider"] = provider
        return content

    async def fetch_yan(self, ctx, tags):  # Yande.re fetcher
        urlstr = "https://yande.re/post.json?limit=100&tags=" + "+".join(tags)
        log.debug(urlstr)
        return await self.fetch_from_booru(urlstr, "Yandere")

    async def fetch_gel(self, ctx, tags):  # Gelbooru fetcher
        urlstr = "https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&limit=100&tags=" + "+".join(tags)
        log.debug(urlstr)
        return await self.fetch_from_booru(urlstr, "Gelbooru")

    async def fetch_safe(self, ctx, tags):  # Safebooru fetcher
        urlstr = "https://safebooru.org/index.php?page=dapi&s=post&q=index&json=1&limit=100&tags=" + "+".join(tags)
        log.debug(urlstr)
        return await self.fetch_from_booru(urlstr, "Safebooru")

    async def fetch_kon(self, ctx, tags):  # Konachan fetcher
        urlstr = "https://konachan.com/post.json?limit=100&tags=" + "+".join(tags)
        log.debug(urlstr)
        return await self.fetch_from_booru(urlstr, "Konachan")

    async def fetch_dan(self, ctx, tags):  # Danbooru fetcher
        if len(tags) > 2:
            return []
        urlstr = "https://danbooru.donmai.us/posts.json?limit=100&tags=" + "+".join(tags)
        log.debug(urlstr)
        return await self.fetch_from_booru(urlstr, "Danbooru")

    async def fetch_r34(self, ctx, tags):  # Rule34 fetcher
        urlstr = "https://rule34.xxx/index.php?page=dapi&s=post&q=index&json=1&limit=100&tags=" + "+".join(tags)
        log.debug(urlstr)
        return await self.fetch_from_booru(urlstr, "Rule34")

    async def fetch_e621(self, ctx, tags):  # e621 fetcher
        urlstr = "https://e621.net/post/index.json?limit=100&tags=" + "+".join(tags)
        log.debug(urlstr)
        return await self.fetch_from_booru(urlstr, "e621")

    async def show_booru(self, ctx, data):  # Shows various info in embed
        mn = len(data)
        if mn == 0:
            await ctx.send("No results.")
        else:

            i = randint(0, mn - 1)

            # Build Embed
            embeds = []

            # Respect simple setting
            simple_booru = await self.config.guild(ctx.guild).simple()
            if simple_booru == "on":
                return await self.show_simple_booru(ctx, i, data)

            num_pages = len(data)
            for page_num, booru in enumerate(data, 1):
                # Set variables for owner/author of post
                booru_author = booru.get("owner") or booru.get("author") or booru.get("uploader_name") or "N/A"
                if booru["provider"] == "Reddit":
                    booru_author = booru["data"]["author"]

                # Set variables for tags
                booru_tags = booru.get("tags") or booru.get("tag_string") or "N/A"
                if booru["provider"] == "Reddit":
                    booru_tags = booru["data"]["title"]

                # Set variables for score
                booru_score = booru.get("score") or "N/A"
                if booru["provider"] == "Reddit":
                    booru_score = booru["data"]["score"]

                # Set variables for file url
                file_url = booru.get("file_url")
                if booru["provider"] == "Rule34":
                     file_url = "https://us.rule34.xxx//images/" + booru.get("directory") + "/" + booru.get("image")
                if booru["provider"] == "Safebooru":
                     file_url = "https://safebooru.org//images/" + booru.get("directory") + "/" + booru.get("image")
                if booru["provider"] == "Reddit":
                     file_url = booru["data"]["url"]
                booru_url = file_url

                # Set variable for post link
                if booru["provider"] == "Konachan":
                    booru_post = "https://konachan.com/post/show/" + str(booru.get("id"))
                if booru["provider"] == "Gelbooru":
                    booru_post = "https://gelbooru.com/index.php?page=post&s=view&id=" + str(booru.get("id"))
                if booru["provider"] == "Rule34":
                    booru_post = "https://rule34.xxx/index.php?page=post&s=view&id=" + str(booru.get("id"))
                if booru["provider"] == "Yandere":
                    booru_post = "https://yande.re/post/show/" + str(booru.get("id"))
                if booru["provider"] == "Danbooru":
                    booru_post = "https://danbooru.donmai.us/posts/" + str(booru.get("id"))
                if booru["provider"] == "Safebooru":
                    booru_post = "https://safebooru.com/index.php?page=post&s=view&id=" + str(booru.get("id"))
                if booru["provider"] == "e621":
                    booru_post = "https://e621.net/post/show/" + str(booru.get("id"))
                if booru["provider"] == "Reddit":
                    booru_post = "https://reddit.com" + booru["data"]["permalink"]

                # Set colour for each board
                color = {"Gelbooru": 3395583, "Danbooru": 3395583, "Konachan": 8745592, "Yandere": 2236962, "Rule34": 339933, "Safebooru": 000000, "e621": 000000, "Reddit": 000000}

                embed = discord.Embed()
                embed.color = color[booru["provider"]]
                embed.title = booru["provider"] + " entry by " + booru_author
                embed.url = booru_post
                embed.set_image(url=booru_url)
                embed.add_field(name="Description / Tags", value="```" + booru_tags[:300] + "```", inline=False)
                embed.add_field(name="Rating", value=booru["rating"])
                embed.add_field(name="Score", value=booru_score)
                if booru["provider"] == "Reddit":
                    embed.set_footer(text=f"{page_num}/{num_pages} If image doesn't appear, it may be a webm or too big, Powered by {booru['data']['subreddit_name_prefixed']}")
                else:
                    embed.set_footer(text=f"{page_num}/{num_pages} If image doesn't appear, it may be a webm or too big, Powered by {booru['provider']}")
                embeds.append(embed)

            await menu(ctx, pages=embeds, controls=DEFAULT_CONTROLS, message=None, page=i, timeout=15)

    async def show_simple_booru(self, ctx, i, data):  # Shows simple embed

            booru = data[i]

            # Set variables for file url
            file_url = booru.get("file_url")
            if booru["provider"] == "Rule34":
                 file_url = "https://us.rule34.xxx//images/" + booru.get("directory") + "/" + booru.get("image")
            if booru["provider"] == "Safebooru":
                 file_url = "https://safebooru.org//images/" + booru.get("directory") + "/" + booru.get("image")
            if booru["provider"] == "Reddit":
                 file_url = booru["data"]["url"]
            booru_url = file_url

            # Set colour for each board
            color = {"Gelbooru": 3395583, "Danbooru": 3395583, "Konachan": 8745592, "Yandere": 2236962, "Rule34": 339933, "Safebooru": 000000, "e621": 000000, "Reddit": 000000}

            embed = discord.Embed()
            embed.color = color[booru["provider"]]
            embed.set_image(url=booru_url)
            await ctx.send(embed=embed)