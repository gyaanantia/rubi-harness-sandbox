from scenarios import day1_screen, day2_repeat, sync_failure, unattended

SCENARIOS = {
    scenario.__name__.rsplit(".", 1)[-1]: scenario
    for scenario in [day1_screen, day2_repeat, unattended, sync_failure]
}
