from match_process import MatchStatus
from modules.reactions import ReactionHandler

from display import AllStrings as disp, ContextWrapper

import discord.errors

import match_process.meta as meta
import match_process.common_picking as common
from asyncio import sleep

import modules.accounts_handler as accounts
import modules.database as db
import modules.config as cfg
import modules.census as census

class GettingReady(meta.Process, status=MatchStatus.IS_WAITING):

    def __init__(self, match):
        self.match = match

        self.match.teams[1].captain.is_turn = True
        self.match.teams[0].captain.is_turn = True

        self.sub_handler = common.SubHandler(self.match.proxy, self.do_sub)

        super().__init__(match)

    @meta.init_loop
    async def init(self):
        await disp.ACC_SENDING.send(self.match.channel)

        for tm in self.match.teams:
            for a_player in tm.players:
                if not a_player.has_own_account:
                    success = await accounts.give_account(a_player)
                    if success:
                        self.match.players_with_account.append(a_player)
                    else:
                        await disp.ACC_NOT_ENOUGH.send(self.match.channel)
                        await self.clear()
                        return

        # Try to send the accounts:
        for a_player in self.match.players_with_account:
            await accounts.send_account(self.match.channel, a_player)

        await disp.ACC_SENT.send(self.match.channel)

        await disp.MATCH_CONFIRM.send(self.match.channel, self.match.teams[0].captain.mention,
                                      self.match.teams[1].captain.mention, match=self.match.proxy)

    @meta.public
    async def clear(self, ctx):
        await self.sub_handler.clean()
        await self.match.clean()
        await disp.MATCH_CLEARED.send(ctx)

    @meta.public
    async def team_ready(self, ctx, captain):
        if not captain.is_turn:
            self.on_team_ready(captain.team, False)
            await disp.MATCH_TEAM_UNREADY.send(ctx, captain.team.name, match=self.match.proxy)
        if captain.is_turn:
            if self.match.check_validated:
                not_validated_players = accounts.get_not_validated_accounts(captain.team)
                if len(not_validated_players) != 0:
                    await disp.MATCH_PLAYERS_NOT_READY.send(ctx, captain.team.name,
                                                            " ".join(p.mention for p in not_validated_players))
                    return
            if self.match.check_offline:
                offline_players = await census.get_offline_players(captain.team)
                if len(offline_players) != 0:
                    await disp.MATCH_PLAYERS_OFFLINE.send(ctx, captain.team.name,
                                                          " ".join(p.mention for p in offline_players),
                                                          p_list=offline_players)
                    return
            self.on_team_ready(captain.team, True)
            await disp.MATCH_TEAM_READY.send(ctx, captain.team.name, match=self.match.proxy)
            return

    def on_team_ready(self, team, ready):
        team.captain.is_turn = not ready
        team.on_team_ready(ready)
        if ready:
            other = self.match.teams[team.id-1]
            # If other is_turn, then not ready
            # Else everyone ready
            if not other.captain.is_turn:
                self.match.on_ready()

    @meta.public
    async def remove_account(self, a_player):
        await accounts.terminate_account(a_player)
        self.match.players_with_account.remove(a_player)

    @meta.public
    async def give_account(self, a_player):
        success = await accounts.give_account(a_player)
        if success:
            self.match.players_with_account.append(a_player)
            await accounts.send_account(self.match.channel, a_player)
            await disp.ACC_GIVING.send(self.match.channel, a_player.mention)
        else:
            await disp.ACC_NOT_ENOUGH.send(self.match.channel)
            await self.clear()

    @meta.public
    async def sub_request(self, ctx, captain, args):
        await self.sub_handler.sub_request(ctx, captain, args)

    async def do_sub(self, subbed, force_player):
        new_player = await common.after_pick_sub(self.match, subbed, force_player, clean_subbed=False)
        if not new_player:
            return
        if not subbed.active.has_own_account:
            await self.remove_account(subbed.active)
            subbed.on_player_clean()
        if not new_player.active.has_own_account:
            await self.give_account(new_player.active)

    @meta.public
    async def pick_status(self, ctx):
        await disp.PK_FACTION_INFO.send(ctx)

    @meta.public
    async def pick(self, ctx, captain, args):
        await common.faction_change(ctx, captain, args, self.match)
