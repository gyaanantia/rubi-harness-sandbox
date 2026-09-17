from scenarios import day1_screen, day2_remember, day2_repeat, sync_failure, unattended

SCENARIOS = {
    scenario.__name__.rsplit(".", 1)[-1]: scenario
    for scenario in [day1_screen, day2_repeat, day2_remember, unattended, sync_failure]
}
