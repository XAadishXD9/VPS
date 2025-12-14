import discord
from discord.ext import commands
from discord import app_commands
import docker
import asyncio
import os
import time

# ---------------- CONFIG ----------------
TOKEN = "YOUR_BOT_TOKEN"
OWNER_ID = "1405778722732376176"
PASSWORD = "root"
DOCKER_NETWORK = "bridge"
database_file = "database.txt"
ADMIN_IDS = {"1405778722732376176"}

# ---------------- DISCORD SETUP ----------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)
client_docker = docker.from_env()

# ---------------- UTILITY FUNCTIONS ----------------
def add_to_database(userid, container_name, ssh_command):
    with open(database_file, "a") as f:
        f.write(f"{userid}|{container_name}|{ssh_command}\n")

def remove_from_database(container_name):
    if not os.path.exists(database_file):
        return
    with open(database_file, "r") as f:
        lines = f.readlines()
    with open(database_file, "w") as f:
        for line in lines:
            if container_name not in line:
                f.write(line)

def get_user_servers(userid):
    if not os.path.exists(database_file):
        return []
    servers = []
    with open(database_file, "r") as f:
        for line in f:
            if line.startswith(userid):
                servers.append(line.strip())
    return servers

def get_container_id_from_database(userid, container_name):
    servers = get_user_servers(userid)
    for s in servers:
        _, cname, _ = s.split("|")
        if cname == container_name:
            return cname
    return None

# ---------------- DEPLOY VPS ----------------
async def deploy_vps(interaction: discord.Interaction, ram: int, cpu: int, disk: int, user: str):
    await interaction.response.send_message("Creating VPS, please wait...", ephemeral=True)

    memory_bytes = ram * 1024 * 1024 * 1024
    vps_id = str(int(time.time()))
    
    try:
        container = client_docker.containers.run(
            image="ubuntu-22.04-with-tmate",
            name=f"zxnodes-{vps_id}",
            privileged=True,
            hostname=f"zxnodes-{vps_id}",
            mem_limit=memory_bytes,
            cpu_period=100000,
            cpu_quota=int(cpu * 100000),
            cap_add=["ALL"],
            command="tail -f /dev/null",
            tty=True,
            network=DOCKER_NETWORK,
            volumes={f'zxnodes-{vps_id}': {'bind': '/data', 'mode': 'rw'}},
            restart_policy={"Name": "always"}
        )

        # Start tmate
        exec_cmd = await asyncio.create_subprocess_exec(
            "docker", "exec", container.name, "tmate", "-F",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        async def capture_line(process):
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line = line.decode().strip()
                if "ssh session:" in line:
                    return line.split("ssh session:")[1].strip()
            return None

        tmate_line = await capture_line(exec_cmd)

        if tmate_line:
            target_user = await bot.fetch_user(int(user))
            await target_user.send(
                f"Username 👤 : {target_user.name}\n"
                f"RAM: {ram}GB | CPU: {cpu} cores | Disk: {disk}GB\n"
                f"Password: {PASSWORD}\n"
                f"SSH:\n```{tmate_line}```"
            )
            add_to_database(user, container.name, tmate_line)
            await interaction.followup.send(f"VPS deployed successfully and DM sent to {target_user.name}.")
        else:
            await interaction.followup.send("Failed to get tmate session line.")
            container.remove(force=True)
            
    except Exception as e:
        await interaction.followup.send(f"Error creating VPS: {e}")

# ---------------- /deploy COMMAND ----------------
@bot.tree.command(name="deploy", description="Deploy a VPS with RAM, CPU, Disk, and assign to a user.")
@app_commands.describe(
    ram="RAM in GB (e.g., 2)",
    cpu="CPU cores (e.g., 2)",
    disk="Disk in GB (e.g., 10)",
    user="Discord User ID to assign the VPS"
)
async def deploy_command(interaction: discord.Interaction, ram: int, cpu: int, disk: int, user: str):
    await deploy_vps(interaction, ram, cpu, disk, user)

# ---------------- /list COMMAND ----------------
@bot.tree.command(name="list", description="List all your VPS instances.")
async def list_vps(interaction: discord.Interaction):
    userid = str(interaction.user.id)
    servers = get_user_servers(userid)

    if servers:
        embed = discord.Embed(title=f"{interaction.user.name}'s VPS Instances", color=0x00ff00)
        for s in servers:
            _, container_name, _ = s.split("|")
            try:
                container = client_docker.containers.get(container_name)
                status = container.status
            except:
                status = "Not Found"
            embed.add_field(name=container_name, value=f"Status: {status}", inline=False)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("You have no VPS instances.", ephemeral=True)

# ---------------- /vps_list COMMAND (Admin Only) ----------------
@bot.tree.command(name="vps_list", description="List all VPS instances (Admin only).")
async def vps_list(interaction: discord.Interaction):
    if str(interaction.user.id) not in ADMIN_IDS:
        await interaction.response.send_message("You do not have permission.", ephemeral=True)
        return

    if not os.path.exists(database_file):
        await interaction.response.send_message("No VPS instances found.", ephemeral=True)
        return

    embed = discord.Embed(title="All VPS Instances", color=0x00ff00)
    with open(database_file, "r") as f:
        for line in f:
            user, container_name, ssh = line.strip().split("|")
            try:
                container = client_docker.containers.get(container_name)
                status = container.status
            except:
                status = "Not Found"
            embed.add_field(name=container_name, value=f"Owner: {user}\nStatus: {status}", inline=False)
    await interaction.response.send_message(embed=embed)

# ---------------- /manage COMMAND ----------------
@bot.tree.command(name="manage", description="Manage a specific VPS by ID.")
@app_commands.describe(vps_id="VPS container ID to manage", action="Action: start, stop, restart, remove")
async def manage_vps(interaction: discord.Interaction, vps_id: str, action: str):
    userid = str(interaction.user.id)
    container_id = get_container_id_from_database(userid, vps_id)

    if not container_id:
        await interaction.response.send_message("VPS not found or not owned by you.", ephemeral=True)
        return

    try:
        container = client_docker.containers.get(container_id)
        action = action.lower()
        if action == "start":
            container.start()
            await interaction.response.send_message(f"VPS `{vps_id}` started.")
        elif action == "stop":
            container.stop()
            await interaction.response.send_message(f"VPS `{vps_id}` stopped.")
        elif action == "restart":
            container.restart()
            await interaction.response.send_message(f"VPS `{vps_id}` restarted.")
        elif action == "remove":
            container.remove(force=True)
            remove_from_database(container_id)
            await interaction.response.send_message(f"VPS `{vps_id}` removed.")
        else:
            await interaction.response.send_message("Invalid action. Use: start, stop, restart, remove.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error managing VPS: {e}", ephemeral=True)

# ---------------- ON READY ----------------
@bot.event
async def on_ready():
    print(f"Bot is ready! Logged in as {bot.user}")
    await bot.tree.sync()

# ---------------- RUN BOT ----------------
bot.run(TOKEN)
