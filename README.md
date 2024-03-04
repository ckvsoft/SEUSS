![Logo](views/static/images/logo-seuss.png?raw=true "SEUSS")
# SEUSS
### [SEUSS -> Smart Ess Unit Spotmarket Switcher]

#### Please report the bugs and suggest improvements. Thank you to everyone who has already taken part.
###### If you would like to contribute extensions to this, please submit the pull request in the dev branch. For bug fixes, the pull request can also be made on the main branch

### What does this software do?  
This is a Python 3 Application that turns on your ESS unit (controller) at the right time when your hourly dynamic energy prices are low. Or used for discharging when prices are extremely high.

#### Currently supported systems are:
### ESS Units

___
- ***Victron Venus OS energy storage systems such as the MultiPlus II series***
___

### Spot Markets
___
- ***aWATTar***
- ***Entso-E***
- ***Tibber***
___
The control of the ESS unit (controller) is done via mqtt. The advantage of this control is:
that this application does not have to run directly on VenusOS. Direct control with D-BUS is in the works


# Tested 
This version was successful with
___
- ***Linux Ubuntu >= 22.04***
- ***Venus OS Raspberry >= v3.12***
___
tested

# Install
Download the install script from the GitHub repository execute the following command in your terminal:

```
wget -O seuss_install.sh https://raw.githubusercontent.com/ckvsoft/SEUSS/dev/scripts/seuss_install.sh`
```
Run the installer script with additional options to prepare everything in a subdirectory for your inspection. For example:
```
bash seuss_install.sh`
```
The default directory is /data/seuss (Venus OS) But you can optionally specify a different directory by using the environment variable TARGET_DIRECTORY e.g.
```
TARGET_DIRECTORY=/opt/seuss bash seuss_install.sh`
```
On a Cerbo GX the filesystem is mounted read only. See [https://www.victronenergy.com/live/ccgx:root_access](https://www.victronenergy.com/live/ccgx:root_access).
In order to make the filesystem writeable you need to execute the following command before running the install script:
```
/opt/victronenergy/swupdate-scripts/resize2fs.sh
```
# Configuration
After `SEUSS` has been successfully installed, a website is available at the IP address and port 5000 of the `Computer/VenusOS` on which `SEUSS` was installed.
- You can view or download the log file.
- Furthermore, the configuration can be carried out using the [Config Editor] menu item.
- Tool tips for most points are displayed here.

#### Log Viewer
- ![Logo](views/static/images/logviewer.png?raw=true "SEUSS Log Viewer")
#### Config Editor - ESS Units
- ![Logo](views/static/images/configeditor_ess.png?raw=true "SEUSS Config Editor")
#### Config Editor - PV Panels
- ![Logo](views/static/images/configeditor_panels.png?raw=true "SEUSS Config Editor")


These can also be found in the Settings description.
For those who prefer to work in a config file, there is config.json

# Settings
## General
| Setting         | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                             |
|-----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `time_zone`     | Essential for correct timing of operations based on your geographic location.<br/> Format like `Europe/Vienna`, `Europe/Amsterdam`, ...                                                                                                                                                                                                                                                                                                             |
| `log_file_path` | Sets an alternative path to which the log files are saved.                                                                                                                                                                                                                                                                                                                                                                                          |
| `log_level`     | Used Loglevel are: `INFO`, `WARNING`, `ERROR` and `DEBUG`. see [Log Levels](#loglevels)                                                                                                                                                                                                                                                                                                                                                             |

## Prices
#### Please change prices (always use Cent/kWh, no matter if youre using Awattar (displaying Cent/kWh) or Entsoe API (displaying EUR/MWh) / net prices excl. tax).
| Setting                                    | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
|--------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `use_second_day`                           | `enable/disable` to compare today and tomorrow prices if they become available<br/>Note: If you activate this and the prices decrease over several days,it is possible that there will be no charging or switching for several days until the lowest prices are reached.                                                                                                                                                                                                                                                                                 |
| `number_of_lowest_prices_for_charging`     | Two modes can be used here.<br/>mode1:<br/>* the number of cheapest prices at which charging should/may take place. Here you enter whole numbers<br/>mode2:<br/>* Here the number of prices is determined based on the average price. For this mode you enter decimal numbers. E.g. 0.85 to receive all prices that are 85% below average.What is relevant here is the specification of a comma value. With 1.0 it is assumed that 100% of the average price is taken (doesn't make any sense) but if 1 is entered it is 1 cheapest price                     |
| `number_of_highest_prices_for_discharging` | Two modes can be used here.<br/>mode1:<br/>* the number of most expensive prices at which discharging should/may take place. Here you enter whole numbers<br/>mode2:<br/>* Here the number of prices is determined based on the average price. For this mode you enter decimal numbers. E.g. 1.25 to receive all prices that are 25% above average.<br/>What is relevant here is the specification of a comma value. With 1.0 it is assumed that 100% of the average price is taken (doesn't make any sense) but if 1 is entered it is 1 most expensive price |
| `charging_price_limit`                     | charging is always enabled below this price<br/> the number of the most expensive prices at which discharging should/may be carried out                                                                                                                                                                                                                                                                                                                                                                                                                  |

## ESS Units
### Victron
| Setting               | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                  |
|:----------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `use_vrm`             | If this point is enabled (true), an attempt is made to connect to the Victron via the VRM portal.<br/>This requires a user/password in the VRM portal                                                                                                                                                                                                                                                                    |
| `ip_address`          | The local IP address of the Victron.<br/>This is required if `use_vrm` is disabled (false).<br/>Otherwise this field remains empty                                                                                                                                                                                                                                                                                       |
| `unit_id`             | VRM Portal ID<br/>can be found in the `Settings / VRM online portal / VRM Portal Id`.<br/>Note: This ID is required to access the Victron even if you are not using a VRM portal                                                                                                                                                                                                                                         |
| `user`                | mail adress you use to connect to VRM portal                                                                                                                                                                                                                                                                                                                                                                             |
| `password`            | password you use to connect to VRM portal                                                                                                                                                                                                                                                                                                                                                                                |
| `max_discharge_power` | Default: -1<br/>If you use `Limit inverter power` in the ESS menu then this value must be entered here.<br/>If the inverter is set to `Discharge false` by this app then this value will be overwritten in the ESS.<br/>This limit here is set in discharge mode in the ESS.<br/>If no limit is set then leave the value at `-1`.<br/>Example: Enter `1000` to limit the discharge to `1000W`, Enter `-1` for full Power |
| `only_observation`    | If `only observation` is activated the essunit will only be used for statistical purposes. The essunit does not execute any conditions                                                                                                                                                                                                                                                                                     |
| `enabled`             | To use this entry it must be `enabled`. Otherwise `disabled`                                                                                                                                                                                                                                                                                                                                                             |

## Spot Markets
### aWATTar
| Setting      | Meaning                                                              |
|:-------------|:---------------------------------------------------------------------|
| `country`    | Choose location AT or DE                                             |
| `primary`    | If this market is enabled this point sets it as the primary market   |
| `enabled`    | To use this entry it must be `enabled`. Otherwise `disabled`         |

### Entso-e
| Setting      | Meaning                                                                                                                                                                                                                                                                                                                                                                                              |
|:-------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `api_token`  | How to get the free api_security_token:<br/>1. Go to https://transparency.entsoe.eu/ --> register and create an account<br/>2. Send an email to transparency@entsoe.eu with “Restful API access” in the subject line<br/>3. The ENTSO-E Helpdesk will respond to your request within 3 working days.<br/>4. Generate a security token at https://transparency.entsoe.eu/usrm/user/myAccountSettings  |
| `in_domain`  | To find out your in and out domain key go to:<br/>https://www.entsoe.eu/data/energy-identification-codes-eic/eic-area-codes-map/                                                                                                                                                                                                                                                                     |
| `out_domain` | like `in_domain`                                                                                                                                                                                                                                                                                                                                                                                     |
| `primary`    | If this market is enabled this point sets it as the primary market                                                                                                                                                                                                                                                                                                                                   |
| `enabled`    | To use this entry it must be `enabled`. Otherwise `disabled`                                                                                                                                                                                                                                                                                                                                         |

### Tibber
| Setting      | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
|:-------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `api_token`  | To get the tibber_api_key:<br/>1. log in with a free or customer Tibber account at https://developer.tibber.com/settings/access-token<br/>2. Create a token by selecting the scopes you need (select "price")<br/>3. Use this link to create a free account with your smartphone: https://tibber.com/de/invite/ojgfbx2e                                                                                                                                  |
| `price_unit` | Set to:<br/>"energy" to use the spotmarket-prices (default),<br/>"total" to use the total prices including taxes and fees,<br/>"tax" to use only the taxes and fees                                                                                                                                                                                                                                                                                      |
| `primary`    | If this market is enabled this point sets it as the primary market                                                                                                                                                                                                                                                                                                                                                                                       |
| `enabled`    | To use this entry it must be `enabled`. Otherwise `disabled`                                                                                                                                                                                                                                                                                                                                                                                             |

## PV Panels
| Setting           | Meaning                                                                                        |
|:------------------|:-----------------------------------------------------------------------------------------------|
| `locLat`          | Latitude                                                                                       |
| `locLong`         | Longitude                                                                                      |
| `angle`           | Angle of your panels 0 (horizontal) … 90 (vertical)                                            |
| `direction`       | Plane azimuth, -180 … 180 (-180 = north, -90 = east, 0 = south, 90 = west, 180 = north)        |
| `totPower`        | installed modules power in kilo watt                                                           |
| `total_area`      | Total area of the panels in square meters                                                      |
| `damping_morning` | With this parameter you can adjust the result in the morning. Value float 0..1, default 0      |
| `damping_evening` | With this parameter you can adjust the result in the evening. Value float 0..1, default 0      |
| `enabled`         | To use this entry it must be `enabled`. Otherwise `disabled`                                   |

***
## Loglevels
### `ERROR`
The `ERROR` log level indicates error conditions within an application that hinder the execution of a specific operation. While the application can continue functioning at a reduced level of functionality or performance,<br/>`ERROR` logs signify issues that should be investigated promptly.

### `WARN`
Events logged at the `WARN` level typically indicate that something unexpected has
occurred, but the application can continue to function normally for the time being.
It is also used to signify conditions that should be promptly addressed before they
escalate into problems for the application.

### `INFO`
The `INFO` level captures events in the system that are significant to the
application's business purpose. Such events are logged to show that the system is
operating normally. Production systems typically default to logging at this level
so that a summary of the application's normal behavior is visible to anyone
 reviewing the logs.

### `DEBUG`
The `DEBUG` level is used for logging messages that aid developers in identifying
issues during a debugging session. The content of the messages logged at the DEBUG
level will vary depending on your application, but they typically contain
detailed information that assists its developers in troubleshooting problems
efficiently. This can include variables' state within the surrounding scope or
relevant error codes.                                                                                                                                    |

## Inspiration
The idea is inspired by the @christian1980nrw project linked below. This project is my first with the Victron Venus OS, so I adopted some ideas and approaches from the following projects. The approach is the same and for very narrow systems the implementation with a bash script is probably better
##### – thank you very much for passing on the knowledge:
- [Spotmarket-Switcher](https://github.com/christian1980nrw/Spotmarket-Switcher)
- [dynamic-ess](https://github.com/tfranssen/dynamic-ess)
