"""
Automatic watering system python plugin for Domoticz
Author: szelessavmuhely.hu,
Version: 1.4.0 (2026-11-19) 

<plugin key="AWS_OA" name="Automatic watering system _ Öntöző automata" author="szelessavmuhely.hu" version="1.4.0">
	<description>
		<h2>Automatic watering system _ Öntöző automata</h2><br/>
		<br/>
		<br/>
		 Depending on the amount of rain in the past and the next 24 hours, it automatically starts watering for the desired time, even in a repeating cycle. / Az elmúlt és a jövendő 24 óra eső mennyiségének függvényében automatikusan inditja a kivánt idejig akár ismétlödő ciklusban az öntözést
		<br/>
	</description>
	<params>
		<param field="Address" label="Domoticz IP Address" width="200px" required="true" default="127.0.0.1"/>
		<param field="Port" label="Port" width="40px" required="true" default="8080"/>
		<param field="Username" label="Username" width="200px" required="false" default=""/>
		<param field="Password" label="Password" width="200px" required="false" default=""/>
		<param field="Mode1" label="Öntöző szelep(ek) / Irrigation switch(s) (csv list of idx)" width="200px" default=""/>
		<param field="Mode2" label="Talajnedvesség mérő(k) / Soil moisture meter(s) (csv list of idx)" width="200px" default=""/>
		<param field="Mode3" label="Logging Level" width="200px">
			<options>
				<option label="Normal" value="Normal"  default="true"/>
				<option label="Verbose" value="Verbose"/>
				<option label="Debug - Python Only" value="2"/>
				<option label="Debug - Basic" value="62"/>
				<option label="Debug - Basic+Messages" value="126"/>
				<option label="Debug - Connections Only" value="16"/>
				<option label="Debug - Connections+Queue" value="144"/>
				<option label="Debug - All" value="-1"/>
			</options>
		</param>
	</params>
</plugin>
"""
import Domoticz
import json
from urllib import parse, request
from datetime import datetime, timedelta
import time
import math
import base64
import itertools
import re
import os
import heapq

class deviceparam:

	def __init__(self, unit, nvalue, svalue):
		self.unit = unit
		self.nvalue = nvalue
		self.svalue = svalue

class switchparam:

	def __init__(self, idx, command):
		self.idx = idx
		self.command = command

class TranslationLoader:

	def __init__(self, language="en"):
		self.translations = self.load_translations(language)
		if not self.translations:
			Domoticz.Debug("An error occurred while loading the translations!")
			self.translations = self.load_translations("en") 

	def load_translations(self, language):
		file_path = os.path.join(Parameters["HomeFolder"], f'aws_translate_{language}.json')
		try:
			with open(file_path, 'r', encoding='utf-8') as file:
				return json.load(file)
		except (FileNotFoundError, json.JSONDecodeError) as e:
			Domoticz.Debug(f"Error loading the file '{file_path}': {e}")
			return {} 

	def t(self, text):
		return self.translations.get(text, text)  # If there is no translation, it returns with the original text

class BasePlugin:

	def __init__(self):

		self.debug = True
		self.statussupported = hasattr(Domoticz, "Status")
		self.soil_moisture_meter = []
		self.soil_moisture_data = 0.0
		self.soil_moisture_limit = None
		self.weather_valid = False
		self.Frissitesiciklus = 30
		self.nextupdate = datetime.now()
		self.start_time = None
		self.start_minute = None
		self.watering_time = None
		self.cycle_number = None
		self.past_24_hours = 0.0
		self.next_24_hours = 0.0
		self.past_24_hours_limit = None
		self.next_24_hours_limit = None
		self.met_data_string = None
		self.max_met_data = None
		self.watering_valve = []
		self.switchcreated = []
		self.statuscreated = []
		return


	def onStart(self):

		self.location = Settings["Location"].split(";")
		
		tl = TranslationLoader(Parameters["Language"])

		self.watering_valve = parseCSV(Parameters["Mode1"])

		self.soil_moisture_meter = parseCSV(Parameters["Mode2"])


		# állítsa be a megfelelő naplózási szintet
		try:
			debuglevel = int(Parameters["Mode3"])
		except ValueError:
			debuglevel = 0
			self.loglevel = Parameters["Mode3"]
		if debuglevel != 0:
			self.debug = True
			Domoticz.Debugging(debuglevel)
			DumpConfigToLog()
			self.loglevel = "Verbose"
		else:
			self.debug = False
			Domoticz.Debugging(0)

		devicecreated = []
		if 1 not in Devices:
			Options = {"LevelActions": "||",
				"LevelNames": tl.t("Off|On|Automatic"),
				"LevelOffHidden": "false",
				"SelectorStyle": "0"}
			Domoticz.Device(Name=tl.t("Irrigation switch"), Unit=1, TypeName="Selector Switch", Image=22, Options=Options, Used=1).Create()
			devicecreated.append(deviceparam(1, 0, "0"))
			self.addfavorite(Devices[1].ID)
		if 2 not in Devices:
			Options = {"LevelActions": "||",
				"LevelNames": tl.t("Off|00|01|02|03|04|05|06|07|08|09|10|11|12|13|14|15|16|17|18|19|20|21|22|23|"),
				"LevelOffHidden": "false",
				"SelectorStyle": "1"}
			Domoticz.Device(Name=tl.t("Start time"), Unit=2, TypeName="Selector Switch", Image=21, Options=Options, Used=1).Create()
			devicecreated.append(deviceparam(2, 0, "0"))
		if 3 not in Devices:
			Options = {"LevelActions": "||",
				"LevelNames": tl.t("Off|00|05|10|15|20|25|30|35|40|45|50|55"),
				"LevelOffHidden": "true",
				"SelectorStyle": "1"}
			Domoticz.Device(Name=tl.t("Start minute"), Unit=3, TypeName="Selector Switch", Image=21, Options=Options, Used=1).Create()
			devicecreated.append(deviceparam(3, 0, "10"))
		if 4 not in Devices:
			Options = {"LevelActions": "||",
				"LevelNames": tl.t("Off|1 min|2 min|3 min|4 min|5 min|10 min|15 min|20 min|25 min|30 min"),
				"LevelOffHidden": "true",
				"SelectorStyle": "1"}
			Domoticz.Device(Name=tl.t("Watering time"), Unit=4, TypeName="Selector Switch", Image=21, Options=Options, Used=1).Create()
			devicecreated.append(deviceparam(4, 0, "10"))
		if 5 not in Devices:
			Options = {"LevelActions": "||",
				"LevelNames": tl.t("Off|1x|2x|3x|4x|5|6x|7x|8|9|10x|11x|12x|13x|14x|15x|16x|17x|18x|19x|20x|21x|22x|23x|24x"),
				"LevelOffHidden": "true",
				"SelectorStyle": "1"}
			Domoticz.Device(Name=tl.t("Daily repetitions"), Unit=5, TypeName="Selector Switch", Image=21, Options=Options, Used=1).Create()
			devicecreated.append(deviceparam(5, 0, "10"))
		if 6 not in Devices:
			Options = {"LevelActions": "||",
				"LevelNames": tl.t("Off|1mm|2mm|3mm|4mm|5mm|6mm|7mm|8mm|9mm|10mm|15mm|20mm|25mm|30mm|40mm|50mm"),
				"LevelOffHidden": "false",
				"SelectorStyle": "1"}
			Domoticz.Device(Name=tl.t("Rain limit in the last 24 hours (mm)"), Unit=6, TypeName="Selector Switch", Image=20, Options=Options, Used=1).Create()
			devicecreated.append(deviceparam(6, 0, "0"))
		if 7 not in Devices:
			Options = {"LevelActions": "||",
				"LevelNames": tl.t("Off|1mm|2mm|3mm|4mm|5mm|6mm|7mm|8mm|9mm|10mm|15mm|20mm|25mm|30mm|40mm|50mm"),
				"LevelOffHidden": "false",
				"SelectorStyle": "1"}
			Domoticz.Device(Name=tl.t("Rain limit in the next 24 hours (mm)"), Unit=7, TypeName="Selector Switch", Image=20, Options=Options, Used=1).Create()
			devicecreated.append(deviceparam(7, 0, "0"))
		if 8 not in Devices:
			Options = {"LevelActions": "||",
				"LevelNames": tl.t("Off|5%|10%|15%|20%|25%|30%|35%|40%|45%|50%|55%|60%|65%|70%|75%|80%|85%|90%|95%"),
				"LevelOffHidden": "true",
				"SelectorStyle": "1"}
			Domoticz.Device(Name=tl.t("Soil_moisture_meter limit %"), Unit=8, TypeName="Selector Switch", Image=20, Options=Options, Used=1).Create()
			devicecreated.append(deviceparam(8, 0, "120"))
		if 9 not in Devices:
			Domoticz.Device(Name="Irrigation switch on-off", Unit=9, Type=244, Subtype=73, Switchtype=0, Used=0).Create()
			devicecreated.append(deviceparam(9, 0, "0"))
		if 10 not in Devices:
			Domoticz.Device(Name="Rain the last 24 hours", Unit=10, TypeName="Percentage", Used=0).Create()
			devicecreated.append(deviceparam(10, 0, "0"))
		if 11 not in Devices:
			Domoticz.Device(Name="Rain the next 24 hours", Unit=11, TypeName="Percentage", Used=0).Create()
			devicecreated.append(deviceparam(11, 0, "0"))
		if 12 not in Devices:
			Domoticz.Device(Name="Soil_moisture_percent", Unit=12, TypeName="Percentage", Used=0).Create()
			devicecreated.append(deviceparam(12, 0, "0"))


		for device in devicecreated:
			Devices[device.unit].Update(nValue=device.nvalue, sValue=device.svalue)

		self.parameters()


	def onStop(self):
		Domoticz.Debugging(0)


	def onCommand(self, Unit, Command, Level, Color):

		Domoticz.Debug("onCommand called for Unit {}: Command '{}', Level: {}".format(Unit, Command, Level))

		nvalue = 1 if Level > 0 else 0
		svalue = str(Level)

		Devices[Unit].Update(nValue=nvalue, sValue=svalue)

		if Unit in (1, 2, 3, 4, 5, 6, 7): # újrainditás, ha megváltozik a vezérlésimód
			self.parameters()


	def onHeartbeat(self):

		self.switchcreated.clear()
		self.statuscreated.clear()

		self.readMoisture()
		Domoticz.Debug(f"Talajnedvesség érték: {self.soil_moisture_data} (limit: {self.soil_moisture_limit})")

		self.now = datetime.now()

		if self.nextupdate <= self.now:
			Domoticz.Debug(f"Adat frissites")
			self.nextupdate = self.now + timedelta(minutes=self.Frissitesiciklus)

			self.met_data_string = self.LatLonNapTempAPI()
			self.weather_valid = self.rain_24h()
			if self.weather_valid:
				Devices[10].Update(nValue=0, sValue=str(round(self.past_24_hours, 1)))
				Devices[11].Update(nValue=0, sValue=str(round(self.next_24_hours, 1)))
				Domoticz.Debug(f"Elmúlt 24 óra: {self.past_24_hours:.1f} mm; következő 24 óra: {self.next_24_hours:.1f} mm")

		else:
			Domoticz.Debug(f"Adat frissitésnek nincs még itt az ideje, majd: {self.nextupdate.strftime('%Y-%m-%d %H:%M:%S')}")


		# Manuális ki
		if Devices[1].sValue == "0":
			self.switchValve(False)

		# Manuális be
		elif Devices[1].sValue == "10":
			self.switchValve(True)

		# Automatikus mód
		elif Devices[1].sValue == "20":

			Domoticz.Debug(f"self.max_met_data = {self.max_met_data}")

			Domoticz.Debug(f"soil_moisture_data: {self.soil_moisture_data}")
			Domoticz.Debug(f"soil_moisture_limit: {self.soil_moisture_limit}")

			Domoticz.Debug(f"past_24_hours: {self.past_24_hours}")
			Domoticz.Debug(f"past_24_hours_limit: {self.past_24_hours_limit}")

			Domoticz.Debug(f"next_24_hours: {self.next_24_hours}")
			Domoticz.Debug(f"next_24_hours_limit: {self.next_24_hours_limit}")

			Domoticz.Debug(f"soil_dry: {self.soil_moisture_data <= self.soil_moisture_limit if self.soil_moisture_data is not None else 'N/A'}")

			Domoticz.Debug(
				f"past_rain_limit_exceeded: "
				f"{self.past_24_hours >= self.past_24_hours_limit if self.past_24_hours is not None and self.past_24_hours_limit is not None else 'N/A'}"
			)

			Domoticz.Debug(
				f"future_rain_limit_exceeded: "
				f"{self.next_24_hours >= self.next_24_hours_limit if self.next_24_hours is not None and self.next_24_hours_limit is not None else 'N/A'}"
			)

			# Hiányzó meteorológiai adat esetén ne induljon automatikus öntözés, ha esőhatár aktív.
			if (self.past_24_hours_limit is not None or self.next_24_hours_limit is not None) and not self.weather_valid:
				self.switchValve(False)
				Domoticz.Error("Öntözés tiltva: nincs érvényes Open-Meteo csapadékadat")
				self.switchcommand()
				self.statuscommand()
				return

			# Ha öntözési idő van
			if self.is_watering_time_now():
				Domoticz.Debug("Öntözés időablak aktív")

				if self.soil_moisture_meter:
					
					if self.soil_moisture_limit is None or self.soil_moisture_data <= self.soil_moisture_limit:
						if self.next_24_hours_limit is None:
							self.switchValve(True)
							Domoticz.Debug("Öntözés engedélyezve – talaj száraz, nincs előrejelzett eső")
						elif self.next_24_hours >= self.next_24_hours_limit:
							self.switchValve(False)
							Domoticz.Debug("Öntözés tiltva – bár talaj száraz, sok eső várható")
						else:
							self.switchValve(True)
							Domoticz.Debug("Öntözés engedélyezve – talaj száraz és nem várható sok eső")
					else:
						self.switchValve(False)
						Domoticz.Debug("Öntözés tiltva – talaj elég nedves")

				elif self.max_met_data:

					if ((self.past_24_hours_limit is not None and self.past_24_hours >= self.past_24_hours_limit) or
						(self.next_24_hours_limit is not None and self.next_24_hours >= self.next_24_hours_limit)):
						self.switchValve(False)
						Domoticz.Debug("Öntözés tiltva – túl sok eső volt vagy várható")
					else:
						self.switchValve(True)
						Domoticz.Debug("Öntözés engedélyezve – eső mennyisége nem haladja meg a határt")

				else:
					self.switchValve(True)
					Domoticz.Debug("Öntözés engedélyezve – nincs érzékelő vagy adat, de időablak aktív")
			else:
				self.switchValve(False)
				Domoticz.Debug("Öntözés nem megfelelő időpontban tiltva")
		

		self.switchcommand()
		self.statuscommand()


	def WriteLog(self, message, level="Normal"):

		if (self.loglevel == "Verbose" and level == "Verbose") or level == "Status":
			if self.statussupported:
				Domoticz.Status(message)
			else:
				Domoticz.Log(message)
		elif level == "Normal":
			Domoticz.Log(message)

	def addfavorite(self, deviceidx):

		idx = deviceidx
		DomoticzAPI("idx={}&isfavorite=1&param=makefavorite&type=command".format(idx))

	def removefavorite(self, deviceidx):

		idx = deviceidx
		DomoticzAPI("idx={}&isfavorite=0&param=makefavorite&type=command".format(idx))


	def LatLonNapTempAPI(self):
		# Open-Meteo: 48 órás múlt és 48 órás előrejelzés, UTC időbélyegekkel.
		try:
			latitude = float(self.location[0].strip())
			longitude = float(self.location[1].strip())
			params = parse.urlencode({
				"latitude": latitude,
				"longitude": longitude,
				"hourly": "precipitation",
				"past_days": 2,
				"forecast_days": 2,
				"timeformat": "unixtime",
				"timezone": "GMT"
			})
			url = "https://api.open-meteo.com/v1/forecast?" + params
			req = request.Request(url, headers={"User-Agent": "Domoticz-AWS-OA/1.4"})
			with request.urlopen(req, timeout=10) as response:
				data = json.load(response)
			if data.get("error"):
				raise ValueError(data.get("reason", "Open-Meteo API hiba"))
			hourly = data.get("hourly", {})
			times = hourly.get("time", [])
			values = hourly.get("precipitation", [])
			if not times or len(times) != len(values):
				raise ValueError("Hiányzó vagy eltérő hosszúságú órás csapadékadat")
			return [{"time": int(t), "rain": float(v)} for t, v in zip(times, values) if v is not None]
		except Exception as e:
			Domoticz.Error(f"Open-Meteo adatlekérés sikertelen: {e}")
			return None

	def rain_24h(self):
		if not self.met_data_string:
			return False
		now = time.time()
		past = 0.0
		future = 0.0
		past_coverage = 0.0
		future_coverage = 0.0
		try:
			for item in self.met_data_string:
				# Az órás csapadék a [time, time+3600) intervallumhoz tartozik.
				start = float(item["time"])
				end = start + 3600
				rain = float(item["rain"])
				if not math.isfinite(rain) or rain < 0:
					raise ValueError("Érvénytelen csapadékérték")
				past_seconds = max(0.0, min(end, now) - max(start, now - 86400))
				future_seconds = max(0.0, min(end, now + 86400) - max(start, now))
				past += rain * past_seconds / 3600
				future += rain * future_seconds / 3600
				past_coverage += past_seconds
				future_coverage += future_seconds
			if past_coverage < 86399 or future_coverage < 86399:
				raise ValueError("Nem teljes a múltbeli vagy jövőbeli 24 órás adatsor")
			self.past_24_hours = past
			self.next_24_hours = future
			self.max_met_data = max(item["time"] for item in self.met_data_string) + 3600
			return True
		except Exception as e:
			Domoticz.Error(f"Open-Meteo csapadékfeldolgozási hiba: {e}")
			return False


	def is_watering_time_now(self):

		Domoticz.Debug(f"Indul watering_time")

		if self.start_time is None or self.start_minute is None:
			Domoticz.Debug("Nincs beállítva start_time vagy start_minute – kihagyjuk az időellenőrzést.")
			return False

		if not self.cycle_number or self.cycle_number < 1:
			Domoticz.Debug(f"Hibás cycle_number: {self.cycle_number}")
			return False

		if not self.watering_time:
			Domoticz.Debug(f"Hibás watering_time: {self.watering_time}")
			return False

		now_ts = time.time()

		today_midnight_ts = time.mktime(
			time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")
		)

		start_ts = (
			today_midnight_ts
			+ self.start_time * 3600
			+ self.start_minute * 60
		)

		cycle_interval = 86400 / self.cycle_number

		Domoticz.Debug(
			f"most={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now_ts))}, "
			f"start={self.start_time:02d}:{self.start_minute:02d}, "
			f"cycle_number={self.cycle_number}, "
			f"watering_time={self.watering_time} perc, "
			f"cycle_interval={cycle_interval / 3600:.2f} óra"
		)

		for i in range(self.cycle_number):

			cycle_start = start_ts + i * cycle_interval
			cycle_end = cycle_start + self.watering_time * 60

			Domoticz.Debug(
				f"ciklus {i+1}/{self.cycle_number}: "
				f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cycle_start))} - "
				f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cycle_end))}"
			)

			if cycle_start <= now_ts <= cycle_end:
				Domoticz.Debug(
					f" AKTÍV CIKLUS: {i+1}/{self.cycle_number}"
				)
				return True

		Domoticz.Debug("Jelenleg egyik ciklus sem aktív")
		return False


	def switchValve(self, switch):

		command = "On" if switch else "Off"

		if switch:
			nvalue = 1
			svalue = "On"
		else:
			nvalue = 0
			svalue = "Off"
		
		Devices[9].Update(nValue=nvalue, sValue=svalue)

		for idx in self.watering_valve:
			self.switchappend(idx,command)

	def switchappend(self,idx,command):

		notInList = True
		for switch in self.switchcreated:
			if switch.idx == idx:
				Domoticz.Debug("Ez a kapcsoló már benne van a listában "+ format(idx) +" | "+ format(command))
				if command == "On":
					Domoticz.Debug("%s az érték felül kell írni a %s értékkel" % (switch.command, command))
					switch.command = command
				else:
					Domoticz.Debug("Marad a %s érték" % command)
				notInList = False
				break
		if notInList:
			Domoticz.Debug("Ez a kapcsoló még nincs a listában, hozzá kell adni " + format(idx) +" | "+ format(command))
			self.switchcreated.append(switchparam(idx, command))

	def switchcommand(self):

		devicesAPI = DomoticzAPI(
			"type=devices&filter=light&order=Name" 
			if float(Parameters["DomoticzVersion"].split()[0]) <= 2023.1 
			else "type=command&param=getdevices&filter=light&order=Name"
		)
		if devicesAPI:
			for switch in self.switchcreated:
				# A kapcsoló aktuális állapotonak megállapítása és, annak ellenőrzésére, hogy már a kívánt állapotban van-e?
				for device in devicesAPI["result"]:  # elemzi a kapcsolóeszközt
					deviceidx = int(device["idx"])
					if deviceidx == switch.idx:  # ez az a kapcsoló
						Domoticz.Debug("Kapcsoló " + format(switch.idx)+" "+format(device["Status"]))
						if device["Status"] != format(switch.command) :
							Domoticz.Debug("Szükség van kapcsolásra ")
							DomoticzAPI("type=command&param=switchlight&idx={}&switchcmd={}".format(switch.idx, switch.command))
						else: 
							Domoticz.Debug("Nincs szükség kapcsolásra ")
		

	def switchstatus(self,idx,command):
		notInList = True
		for statusflag in self.statuscreated:
			if statusflag.idx == idx:
				Domoticz.Debug("Ez a status már benne van a listában "+ format(idx) +" | "+ format(command))
				if command == "On":
					Domoticz.Debug("%s az érték felül kell írni a %s értékkel" % (statusflag.command, command))
					statusflag.command = command
				else:
					Domoticz.Debug("Marad a %s érték" % command)
				notInList = False
				break
		if notInList:
			Domoticz.Debug("Ez a status még nincs a listában, hozzá kell adni " + format(idx) +" | "+ format(command))
			self.statuscreated.append(switchparam(idx, command))

	def statuscommand(self):
		devicesAPI = DomoticzAPI(
			"type=devices&filter=light&order=Name" 
			if float(Parameters["DomoticzVersion"].split()[0]) <= 2023.1 
			else "type=command&param=getdevices&filter=light&order=Name"
		)
		if devicesAPI:
			for statusflag in self.statuscreated:
				# A status aktuális állapotonak megállapítása és, annak ellenőrzésére, hogy már a kívánt állapotban van-e?
				for device in devicesAPI["result"]:  # elemzi a kapcsolóeszközt
					deviceidx = int(device["idx"])
					if deviceidx == statusflag.idx:  # ez az a kapcsoló
						Domoticz.Debug("Status " + format(statusflag.idx)+" "+format(device["Status"]))
						if device["Status"] != format(statusflag.command) :
							Domoticz.Debug("Szükség van status váltásra ")
							if format(statusflag.command) == "On":
								nValue = 1
							else :
								nValue = 0

							self.UpdateDevice(device["Unit"],nValue,statusflag.command)
						else: 
							Domoticz.Debug("Nincs szükség status váltásra ")

	def readMoisture(self):

		# lekérni az összes eszközt az API-ból
		noerror = True
		listmoisture = []
		devicesAPI = DomoticzAPI(
			"type=devices&order=Name" 
			if float(Parameters["DomoticzVersion"].split()[0]) <= 2023.1 
			else "type=command&param=getdevices&order=Name"
		)
		if devicesAPI:
			for device in devicesAPI["result"]:
				idx = int(device["idx"])
				if idx in self.soil_moisture_meter:
					if "Humidity" in device:
						Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Humidity"]))
						dmoisture = device["Humidity"]
						listmoisture.append(dmoisture)
					else:
						Domoticz.Error("device: {}-{} is not a moisture sensor".format(device["idx"], device["Name"]))


		nbmoisture = len(listmoisture)
		if nbmoisture > 0:
			self.soil_moisture_data = round(sum(listmoisture) / nbmoisture, 1)

		else:
			Domoticz.Debug("No moisture sensor found...")
			self.soil_moisture_data = 0.0

		svalue = self.soil_moisture_data

		if isinstance(self.soil_moisture_data, (int, float)):
			Devices[12].Update(nValue=0, sValue=str(round(self.soil_moisture_data, 1)))
		else:
			Domoticz.Error("Hibás soil_moisture_data típus: " + str(self.soil_moisture_data))


		Domoticz.Debug(f"self.soil_moisture_data = {svalue}")

		return noerror


	def parameters(self):

		if Devices[2].sValue == "10" :
			self.start_time = 0
		elif Devices[2].sValue == "20" :
			self.start_time = 1
		elif Devices[2].sValue == "30" :
			self.start_time = 2
		elif Devices[2].sValue == "40" :
			self.start_time = 3
		elif Devices[2].sValue == "50" :
			self.start_time = 4
		elif Devices[2].sValue == "60" :
			self.start_time = 5
		elif Devices[2].sValue == "70" :
			self.start_time = 6
		elif Devices[2].sValue == "80" :
			self.start_time = 7
		elif Devices[2].sValue == "90" :
			self.start_time = 8
		elif Devices[2].sValue == "100" :
			self.start_time = 9
		elif Devices[2].sValue == "110" :
			self.start_time = 10
		elif Devices[2].sValue == "120" :
			self.start_time = 11
		elif Devices[2].sValue == "130" :
			self.start_time = 12
		elif Devices[2].sValue == "140" :
			self.start_time = 13
		elif Devices[2].sValue == "150" :
			self.start_time = 14
		elif Devices[2].sValue == "160" :
			self.start_time = 15
		elif Devices[2].sValue == "170" :
			self.start_time = 16
		elif Devices[2].sValue == "180" :
			self.start_time = 17
		elif Devices[2].sValue == "190" :
			self.start_time = 18
		elif Devices[2].sValue == "200" :
			self.start_time = 19
		elif Devices[2].sValue == "210" :
			self.start_time = 20
		elif Devices[2].sValue == "220" :
			self.start_time = 21
		elif Devices[2].sValue == "230" :
			self.start_time = 22
		elif Devices[2].sValue == "240" :
			self.start_time = 23
		
		if Devices[3].sValue == "10" :
			self.start_minute = 0
		elif Devices[3].sValue == "20" :
			self.start_minute = 5
		elif Devices[3].sValue == "30" :
			self.start_minute = 10
		elif Devices[3].sValue == "40" :
			self.start_minute = 15
		elif Devices[3].sValue == "50" :
			self.start_minute = 20
		elif Devices[3].sValue == "60" :
			self.start_minute = 25
		elif Devices[3].sValue == "70" :
			self.start_minute = 30
		elif Devices[3].sValue == "80" :
			self.start_minute = 35
		elif Devices[3].sValue == "90" :
			self.start_minute = 40
		elif Devices[3].sValue == "100" :
			self.start_minute = 45
		elif Devices[3].sValue == "110" :
			self.start_minute = 50
		elif Devices[3].sValue == "120" :
			self.start_minute = 55

		if Devices[4].sValue == "10" :
			self.watering_time = 1
		elif Devices[4].sValue == "20" :
			self.watering_time = 2
		elif Devices[4].sValue == "30" :
			self.watering_time = 3
		elif Devices[4].sValue == "40" :
			self.watering_time = 4
		elif Devices[4].sValue == "50" :
			self.watering_time = 5
		elif Devices[4].sValue == "60" :
			self.watering_time = 10
		elif Devices[4].sValue == "70" :
			self.watering_time = 15
		elif Devices[4].sValue == "80" :
			self.watering_time = 20
		elif Devices[4].sValue == "90" :
			self.watering_time = 25
		elif Devices[4].sValue == "100" :
			self.watering_time = 30


		if Devices[5].sValue == "10" :
			self.cycle_number = 1
		elif Devices[5].sValue == "20" :
			self.cycle_number = 2
		elif Devices[5].sValue == "30" :
			self.cycle_number = 3
		elif Devices[5].sValue == "40" :
			self.cycle_number = 4
		elif Devices[5].sValue == "50" :
			self.cycle_number = 5
		elif Devices[5].sValue == "60" :
			self.cycle_number = 6
		elif Devices[5].sValue == "70" :
			self.cycle_number = 7
		elif Devices[5].sValue == "80" :
			self.cycle_number = 8
		elif Devices[5].sValue == "90" :
			self.cycle_number = 9
		elif Devices[5].sValue == "100" :
			self.cycle_number = 10
		elif Devices[5].sValue == "110" :
			self.cycle_number = 11
		elif Devices[5].sValue == "120" :
			self.cycle_number = 12
		elif Devices[5].sValue == "130" :
			self.cycle_number = 13
		elif Devices[5].sValue == "140" :
			self.cycle_number = 14
		elif Devices[5].sValue == "150" :
			self.cycle_number = 15
		elif Devices[5].sValue == "160" :
			self.cycle_number = 16
		elif Devices[5].sValue == "170" :
			self.cycle_number = 17
		elif Devices[5].sValue == "180" :
			self.cycle_number = 18
		elif Devices[5].sValue == "190" :
			self.cycle_number = 19
		elif Devices[5].sValue == "200" :
			self.cycle_number = 20
		elif Devices[5].sValue == "210" :
			self.cycle_number = 21
		elif Devices[5].sValue == "220" :
			self.cycle_number = 22
		elif Devices[5].sValue == "230" :
			self.cycle_number = 23
		elif Devices[5].sValue == "240" :
			self.cycle_number = 24


		self.past_24_hours_limit = None
		self.next_24_hours_limit = None
		if Devices[6].sValue == "10" :
			self.past_24_hours_limit = 1.0
		elif Devices[6].sValue == "20" :
			self.past_24_hours_limit = 2.0
		elif Devices[6].sValue == "30" :
			self.past_24_hours_limit = 3.0
		elif Devices[6].sValue == "40" :
			self.past_24_hours_limit = 4.0
		elif Devices[6].sValue == "50" :
			self.past_24_hours_limit = 5.0
		elif Devices[6].sValue == "60" :
			self.past_24_hours_limit = 6.0
		elif Devices[6].sValue == "70" :
			self.past_24_hours_limit = 7.0
		elif Devices[6].sValue == "80" :
			self.past_24_hours_limit = 8.0
		elif Devices[6].sValue == "90" :
			self.past_24_hours_limit = 9.0
		elif Devices[6].sValue == "100" :
			self.past_24_hours_limit = 10.0
		elif Devices[6].sValue == "110" :
			self.past_24_hours_limit = 15.0
		elif Devices[6].sValue == "120" :
			self.past_24_hours_limit = 20.0
		elif Devices[6].sValue == "130" :
			self.past_24_hours_limit = 25.0
		elif Devices[6].sValue == "140" :
			self.past_24_hours_limit = 30.0
		elif Devices[6].sValue == "150" :
			self.past_24_hours_limit = 40.0
		elif Devices[6].sValue == "160" :
			self.past_24_hours_limit = 50.0
		
		if Devices[7].sValue == "10" :
			self.next_24_hours_limit = 1.0
		elif Devices[7].sValue == "20" :
			self.next_24_hours_limit = 2.0
		elif Devices[7].sValue == "30" :
			self.next_24_hours_limit = 3.0
		elif Devices[7].sValue == "40" :
			self.next_24_hours_limit = 4.0
		elif Devices[7].sValue == "50" :
			self.next_24_hours_limit = 5.0
		elif Devices[7].sValue == "60" :
			self.next_24_hours_limit = 6.0
		elif Devices[7].sValue == "70" :
			self.next_24_hours_limit = 7.0
		elif Devices[7].sValue == "80" :
			self.next_24_hours_limit = 8.0
		elif Devices[7].sValue == "90" :
			self.next_24_hours_limit = 9.0
		elif Devices[7].sValue == "100" :
			self.next_24_hours_limit = 10.0
		elif Devices[7].sValue == "110" :
			self.next_24_hours_limit = 15.0
		elif Devices[7].sValue == "120" :
			self.next_24_hours_limit = 20.0
		elif Devices[7].sValue == "130" :
			self.next_24_hours_limit = 25.0
		elif Devices[7].sValue == "140" :
			self.next_24_hours_limit = 30.0
		elif Devices[7].sValue == "150" :
			self.next_24_hours_limit = 40.0
		elif Devices[7].sValue == "160" :
			self.next_24_hours_limit = 50.0

		if Devices[8].sValue == "0" :
			self.soil_moisture_limit = None
		elif Devices[8].sValue == "10" :
			self.soil_moisture_limit = 5.0
		elif Devices[8].sValue == "20" :
			self.soil_moisture_limit = 10.0
		elif Devices[8].sValue == "30" :
			self.soil_moisture_limit = 15.0
		elif Devices[8].sValue == "40" :
			self.soil_moisture_limit = 20.0
		elif Devices[8].sValue == "50" :
			self.soil_moisture_limit = 25.0
		elif Devices[8].sValue == "60" :
			self.soil_moisture_limit = 30.0
		elif Devices[8].sValue == "70" :
			self.soil_moisture_limit = 35.0
		elif Devices[8].sValue == "80" :
			self.soil_moisture_limit = 40.0
		elif Devices[8].sValue == "90" :
			self.soil_moisture_limit = 45.0
		elif Devices[8].sValue == "100" :
			self.soil_moisture_limit = 50.0
		elif Devices[8].sValue == "110" :
			self.soil_moisture_limit = 55.0
		elif Devices[8].sValue == "120" :
			self.soil_moisture_limit = 60.0
		elif Devices[8].sValue == "130" :
			self.soil_moisture_limit = 65.0
		elif Devices[8].sValue == "140" :
			self.soil_moisture_limit = 70.0
		elif Devices[8].sValue == "150" :
			self.soil_moisture_limit = 75.0
		elif Devices[8].sValue == "160" :
			self.soil_moisture_limit = 80.0
		elif Devices[8].sValue == "170" :
			self.soil_moisture_limit = 85.0
		elif Devices[8].sValue == "180" :
			self.soil_moisture_limit = 90.0
		elif Devices[8].sValue == "190" :
			self.soil_moisture_limit = 95.0

		Devices[6].Update(nValue=Devices[6].nValue, sValue=Devices[6].sValue, Used=1)
		Devices[7].Update(nValue=Devices[7].nValue, sValue=Devices[7].sValue, Used=1)

		if self.soil_moisture_meter:
			Devices[8].Update(nValue=Devices[8].nValue, sValue=Devices[8].sValue, Used=1)
		else:
			Devices[8].Update(nValue=Devices[8].nValue, sValue=Devices[8].sValue, Used=0)


global _plugin
_plugin = BasePlugin()


def onStart():
	global _plugin
	_plugin.onStart()


def onStop():
	global _plugin
	_plugin.onStop()


def onCommand(Unit, Command, Level, Color):
	global _plugin
	_plugin.onCommand(Unit, Command, Level, Color)


def onHeartbeat():
	global _plugin
	_plugin.onHeartbeat()


# Plugin utility functions ---------------------------------------------------

def parseCSV(strCSV):

	listvals = []
	for value in strCSV.split(","):
		try:
			val = int(value)
		except:
			pass
		else:
			listvals.append(val)
	return listvals


def DomoticzAPI(APICall):

	resultJson = None
	url = "http://{}:{}/json.htm?{}".format(Parameters["Address"], Parameters["Port"], parse.quote(APICall, safe="&="))
	Domoticz.Debug("Calling domoticz API: {}".format(url))
	try:
		req = request.Request(url)
		if Parameters["Username"] != "":
			Domoticz.Debug("Add authentification for user {}".format(Parameters["Username"]))
			credentials = ('%s:%s' % (Parameters["Username"], Parameters["Password"]))
			encoded_credentials = base64.b64encode(credentials.encode('ascii'))
			req.add_header('Authorization', 'Basic %s' % encoded_credentials.decode("ascii"))

		response = request.urlopen(req)
		if response.status == 200:
			resultJson = json.loads(response.read().decode('utf-8'))
			if resultJson["status"] != "OK":
				Domoticz.Error("Domoticz API returned an error: status = {}".format(resultJson["status"]))
				resultJson = None
		else:
			Domoticz.Error("Domoticz API: http error = {}".format(response.status))
	except:
		Domoticz.Error("Error calling '{}'".format(url))
	return resultJson


# Generic helper functions
def DumpConfigToLog():
	for x in Parameters:
		if Parameters[x] != "":
			Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
	Domoticz.Debug("Device count: " + str(len(Devices)))
	for x in Devices:
		Domoticz.Debug("Device:" + str(x) + " - " + str(Devices[x]))
		Domoticz.Debug("Device ID: '" + str(Devices[x].ID) + "'")
		Domoticz.Debug("Device Name: '" + Devices[x].Name + "'")
		Domoticz.Debug("Device nValue: " + str(Devices[x].nValue))
		Domoticz.Debug("Device sValue: '" + Devices[x].sValue + "'")
		Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
	return
